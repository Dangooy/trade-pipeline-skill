"""
understanding/assembler.py — RFQ Canonical → OrderModel 组装

职责：
  1. buyer_matcher 匹配（硬阻断）
  2. 从 config 解析 seller_id / terms_id
  3. 创建 OrderItems（含 item_uuid）
  4. 填充 OrderModel 完整结构
  5. resolve_entities 在 Writer 前做 seller 存在性硬校验（Codex review 二轮 P1#2）

禁止：
  - buyer_id 为 None
  - 绕过 OrderModel 直接传数据给 Writer
  - 让 seller_id 指向不存在的实体（resolve_entities 抛 EntityResolutionError）
"""
from datetime import datetime

from ..models.order_model import (
    OrderModel, OrderRefs, OrderInfo, OrderItem,
    DerivedData, OrderMeta, ResolvedEntities,
)
from .buyer_matcher import match_buyer


class EntityResolutionError(Exception):
    """resolve_entities 阶段实体引用解析失败（如 seller_id 指向不存在的 seller）。

    Codex review 二轮 P1#2：删除 seller 后，CRUD 层已经做了引导（三选一对话框），
    但仅靠 UI 不够——pipeline 末端必须 fail-loud，否则用户仍可生成卖方信息为空的
    单据。本异常即生成时的安全网。

    Attributes:
        entity_type: "seller" / "buyer" / "terms"
        entity_id: 期望但缺失的 ID
        available_ids: 当前 config 里实际存在的 ID 列表（供错误信息引导）
    """

    def __init__(self, entity_type: str, entity_id: str, available_ids: list[str]):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.available_ids = available_ids
        hint = ", ".join(available_ids) if available_ids else "（无）"
        super().__init__(
            f"{entity_type}「{entity_id}」在 config 中不存在。\n"
            f"当前可用的 {entity_type}：{hint}\n"
            f"请到「配置中心」检查 {entity_type} 配置，或调整 format_defaults 引用。"
        )


def assemble(
    rfq: dict,
    config: dict,
    order_no: str,
    hint_buyer_id: str | None = None,
) -> OrderModel:
    """
    RFQ Canonical → OrderModel。

    参数:
        rfq: canonicalize 后的 RFQ dict
        config: 完整 config.yaml dict
        order_no: 订单号
        hint_buyer_id: 显式指定 buyer_id（跳过匹配）

    返回:
        OrderModel 实例

    抛出:
        BuyerMatchError — buyer 匹配失败（硬阻断）
    """
    fmt = rfq.get("format", "standard")
    fmt_defaults = config.get("format_defaults", {}).get(fmt, {})

    # ── 1. buyer 匹配 ──
    buyer_id = match_buyer(
        buyer_name_en=rfq.get("buyer_name_en"),
        buyer_name_ru=rfq.get("buyer_name_ru"),
        buyer_name_cn=rfq.get("buyer_name_cn"),
        config=config,
        hint_buyer_id=hint_buyer_id,
    )

    # ── 2. 构建 refs ──
    # 根据实际货币动态选择 format_defaults
    currency = rfq.get("currency", fmt_defaults.get("currency", "CNY"))
    if fmt == "standard" and currency == "USD":
        fmt_defaults = config.get("format_defaults", {}).get("standard_usd", fmt_defaults)

    # fail-loud：format 未配置 seller_id 时直接抛错，不再用硬编码实体名兜底。
    # 旧 fallback "shengzhenyuan" 已被 resolve_entities 拦截无害化，但魔法字符串
    # 会掩盖"format 配置不完整"的真正问题，且万一真存在同名 seller 会静默命中错误实体。
    # （Codex PR #1 三轮 review 遗留清理项）
    seller_id = fmt_defaults.get("seller_id")
    if not seller_id:
        raise EntityResolutionError(
            entity_type="seller",
            entity_id=f"format_defaults[{fmt!r}].seller_id",
            available_ids=list(config.get("sellers", {}).keys()),
        )
    terms_id = fmt_defaults.get("terms_id", "standard_cny")

    refs = OrderRefs(
        seller_id=seller_id,
        buyer_id=buyer_id,
        terms_id=terms_id,
    )

    # ── 3. 构建 order info ──
    now = datetime.now()
    currency = rfq.get("currency", fmt_defaults.get("currency", "CNY"))
    price_unit = rfq.get("price_unit", fmt_defaults.get("price_unit", "CNY/MPCS"))
    defaults = config.get("defaults", {})

    order = OrderInfo(
        order_no=order_no,
        format=fmt,
        quote_no=defaults.get("quote_no_pattern", "QT-{order_no}").format(order_no=order_no),
        pi_number=defaults.get("pi_number_pattern", "PI-{order_no}").format(order_no=order_no),
        ci_number=defaults.get("ci_number_pattern", "CI-{order_no}").format(order_no=order_no),
        date=now.strftime(defaults.get("date_format", "%d %B %Y")),
        currency=currency,
        price_unit=price_unit,
    )

    # ── 4. 构建 items ──
    items = []
    for i, raw_item in enumerate(rfq.get("items", []), start=1):
        item = OrderItem(
            no=i,
            item_uuid=OrderItem.generate_uuid(),
            part_no=raw_item.get("part_no"),
            standard=raw_item.get("standard"),
            description_raw=raw_item.get("description_raw", ""),
            description=raw_item.get("description", ""),
            quantity=raw_item.get("quantity", 0),
            unit=raw_item.get("unit", "pcs"),
            weight_kg=raw_item.get("weight_kg"),
            barcode=raw_item.get("barcode"),
            qty_box=raw_item.get("qty_box"),
            kg_mpcs=raw_item.get("kg_mpcs"),
            group_key=raw_item.get("group_key", ""),
            din=raw_item.get("din_group") or raw_item.get("standard"),
            unit_price=raw_item.get("unit_price"),
            source_method="excel",
        )
        items.append(item)

    # ── 5. 构建 derived ──
    total_qty = sum(it.quantity for it in items)
    has_weight = rfq.get("has_weight", False)

    derived = DerivedData(
        total_items=len(items),
        total_qty=total_qty,
        has_weight=has_weight,
        port_of_loading=defaults.get("port_of_loading"),
    )

    # ── 6. 构建 meta ──
    meta = OrderMeta(
        source_files=[rfq.get("source_file", "")],
        created_at=now.isoformat(),
        last_modified=now.isoformat(),
        parser_model="rules",
        review_status="clean",
    )

    model = OrderModel(
        refs=refs,
        order=order,
        items=items,
        derived=derived,
        meta=meta,
    )

    return model


def resolve_entities(model: OrderModel, config: dict) -> OrderModel:
    """
    根据 refs 中的 ID 从 config 解析完整的实体信息。
    填充 model.resolved。

    必须在 Writer 使用前调用。

    Codex review 二轮 P1#2：seller_id 在 config["sellers"] 中必须存在；
    否则抛 EntityResolutionError，pipeline 立即中止，避免生成卖方信息为空的单据。
    （buyer / terms 仍允许 fallback 到空——buyer 已经在 buyer_matcher 阶段处理过，
    terms 缺失时下游能容忍空字符串，不会导致业务错单。）
    """
    sellers = config.get("sellers") or {}
    buyers = config.get("buyers") or {}
    terms = config.get("terms_templates") or {}

    # 硬校验：seller 必须存在
    if model.refs.seller_id not in sellers:
        raise EntityResolutionError(
            entity_type="seller",
            entity_id=model.refs.seller_id,
            available_ids=list(sellers.keys()),
        )

    seller = sellers[model.refs.seller_id]
    buyer = buyers.get(model.refs.buyer_id, {})
    terms_data = terms.get(model.refs.terms_id, {})

    # seller bank
    bank = seller.get("bank")

    model.resolved = ResolvedEntities(
        seller=seller,
        buyer=buyer,
        terms=terms_data,
        bank=bank,
    )

    return model
