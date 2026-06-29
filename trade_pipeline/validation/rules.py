"""
validation/rules.py — 生成前检查规则库（MVP：10 条核心规则）

每条规则是一个纯函数 (OrderModel) -> list[CheckResult]，不调用 LLM、
不读外部文件。规则只看 OrderModel 已有信息，发现问题就产出结果，
不修改模型本身。

severity 取值约定：
  - error:   缺了它单据必然出错或无法生成（身份 / 贸易术语 / 单价 / 数量 / 金额）
  - warning: 单据能生成但大概率要返工（目的港 / 非吨价订单缺重量）
  - info:    需要人提一句但机器不替人判断（信用证审单 / 证书需求确认）

重量规则（R007）的分级与既有业务逻辑一致：
  - USD/TON 等吨价订单缺重量 → error（金额公式依赖重量，见 models/amounts.py）
  - 其他计价缺重量 → warning（PI/CI 不受影响，PL 可走装箱 Gateway 补录）
"""
from trade_pipeline.models.amounts import PricingMode, compute_amount
from trade_pipeline.models.order_model import OrderItem, OrderModel
from trade_pipeline.validation.models import CheckResult, Severity


# ── 工具 ────────────────────────────────────────────────────────


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _row_nos(items: list[OrderItem]) -> str:
    """把行号列表格式化成 '1、3、5' 形式给用户看。"""
    return "、".join(str(it.no) for it in items)


# ── 身份与订单头规则 ────────────────────────────────────────────


def check_seller_identity(model: OrderModel) -> list[CheckResult]:
    """R001 公司身份缺失：seller_id 为空时所有单据的卖方抬头无从填起。"""
    if _is_blank(model.refs.seller_id):
        return [CheckResult(
            rule_id="R001",
            severity=Severity.ERROR,
            message="公司身份（卖方）缺失：订单未指定出单公司，无法填写单据抬头与银行信息。",
            field="refs.seller_id",
            suggestion="在配置中心选择出单公司，或在 config.yaml 的 sellers 中确认对应条目。",
        )]
    return []


def check_buyer_identity(model: OrderModel) -> list[CheckResult]:
    """R002 客户身份缺失：buyer_id 为空时收货方 / 抬头无法确定。"""
    if _is_blank(model.refs.buyer_id):
        return [CheckResult(
            rule_id="R002",
            severity=Severity.ERROR,
            message="客户身份（买方）缺失：订单未关联客户，无法填写买方抬头与收货信息。",
            field="refs.buyer_id",
            suggestion="确认客户匹配结果，或在 config.yaml 的 buyers 中补充该客户后重试。",
        )]
    return []


def check_trade_terms(model: OrderModel) -> list[CheckResult]:
    """R003 贸易术语缺失：terms_id 为空时付款方式 / 交货条款整段空白。"""
    if _is_blank(model.refs.terms_id):
        return [CheckResult(
            rule_id="R003",
            severity=Severity.ERROR,
            message="贸易条款缺失：订单未指定贸易术语模板，付款方式与交货条款将整段空白。",
            field="refs.terms_id",
            suggestion="在 config.yaml 的 terms_templates 中选择一个条款模板（如 default_usd）。",
        )]
    return []


def check_destination_port(model: OrderModel) -> list[CheckResult]:
    """R004 目的港缺失：CI / PL 上目的港会留白，客户清关时通常要求补改。"""
    if _is_blank(model.derived.port_of_destination):
        return [CheckResult(
            rule_id="R004",
            severity=Severity.WARNING,
            message="目的港缺失：CI / PL 上的目的港将留白，客户清关时大概率要求补改单据。",
            field="derived.port_of_destination",
            suggestion="与客户确认目的港（如 ST. PETERSBURG, RUSSIA）后填入订单再生成。",
        )]
    return []


# ── 行项目规则 ──────────────────────────────────────────────────


def check_unit_prices(model: OrderModel) -> list[CheckResult]:
    """R005 单价缺失：未报价的行金额无法计算，PI / CI 不应在此状态下签发。"""
    missing = [it for it in model.items if it.unit_price is None]
    if missing:
        return [CheckResult(
            rule_id="R005",
            severity=Severity.ERROR,
            message=f"单价缺失：第 {_row_nos(missing)} 行（共 {len(missing)} 行）未填单价，"
                    f"金额无法计算。",
            field="items[].unit_price",
            suggestion="先在报价单中填好单价并执行价格回写（--price-update），再生成 PI / CI。",
        )]
    return []


def check_quantities(model: OrderModel) -> list[CheckResult]:
    """R006 数量缺失或为 0：数量异常的行会让金额与装箱全部失真。"""
    bad = [it for it in model.items if it.quantity is None or it.quantity <= 0]
    if bad:
        return [CheckResult(
            rule_id="R006",
            severity=Severity.ERROR,
            message=f"数量缺失或为 0：第 {_row_nos(bad)} 行（共 {len(bad)} 行）数量为空或不大于 0。",
            field="items[].quantity",
            suggestion="核对询盘原件，修正这些行的数量；确认不出货的行应从订单中删除。",
        )]
    return []


def check_weights(model: OrderModel) -> list[CheckResult]:
    """R007 重量缺失：吨价订单缺重量金额算不出（error）；
    其他计价只影响 PL 装箱，可走 Gateway 补录（warning）。"""
    missing = [it for it in model.items if it.weight_kg is None or it.weight_kg <= 0]
    if not missing:
        return []

    mode = PricingMode.from_price_unit(model.order.price_unit)
    if mode is PricingMode.PER_TON:
        return [CheckResult(
            rule_id="R007",
            severity=Severity.ERROR,
            message=f"重量缺失：本订单按吨计价（{model.order.price_unit}），"
                    f"第 {_row_nos(missing)} 行（共 {len(missing)} 行）缺重量，金额无法计算。",
            field="items[].weight_kg",
            suggestion="按吨计价的订单必须先补齐各行重量（kg），否则 PI / CI 金额为 0。",
        )]
    return [CheckResult(
        rule_id="R007",
        severity=Severity.WARNING,
        message=f"重量缺失：第 {_row_nos(missing)} 行（共 {len(missing)} 行）缺重量。"
                f"PI / CI 不受影响，但生成 PL 时需要补录装箱信息。",
        field="items[].weight_kg",
        suggestion="可现在补齐重量，或生成 PL 时通过装箱信息 Gateway 逐项补录。",
    )]


def check_amounts(model: OrderModel) -> list[CheckResult]:
    """R008 金额为 0 或异常：对已填单价的行按统一金额规则试算，
    结果不大于 0 说明输入组合有问题（单价为 0 / 负数、吨价缺重量等）。"""
    priced = [it for it in model.items if it.unit_price is not None]
    bad = [
        it for it in priced
        if compute_amount(model.order.price_unit, it.quantity, it.weight_kg, it.unit_price) <= 0
    ]
    if bad:
        return [CheckResult(
            rule_id="R008",
            severity=Severity.ERROR,
            message=f"金额为 0 或异常：第 {_row_nos(bad)} 行（共 {len(bad)} 行）已填单价"
                    f"但按 {model.order.price_unit} 规则试算金额不大于 0。",
            field="items[].amount",
            suggestion="检查这些行的单价是否为 0 或负数；按吨计价时同时检查重量是否缺失。",
        )]
    return []


# ── 人工审单提示规则 ────────────────────────────────────────────

_LC_KEYWORDS = ("L/C", "LETTER OF CREDIT", "信用证")


def check_lc_manual_review(model: OrderModel) -> list[CheckResult]:
    """R009 信用证订单提示人工审单：只提醒，不自动判断信用证条款。

    触发信号（任一）：order.lc_number 已填；resolved.terms 的付款方式
    文本中出现信用证关键词。
    """
    signals = []
    if not _is_blank(model.order.lc_number):
        signals.append(f"信用证号 {model.order.lc_number}")
    if model.resolved is not None:
        payment = str((model.resolved.terms or {}).get("payment", ""))
        if any(kw in payment.upper() for kw in _LC_KEYWORDS):
            signals.append("付款条款含信用证字样")
    if signals:
        return [CheckResult(
            rule_id="R009",
            severity=Severity.INFO,
            message=f"信用证订单（{'；'.join(signals)}）：单据必须与信用证条款逐字一致，"
                    f"请在签发前人工逐项核对，本工具不自动判断信用证条款。",
            field="order.lc_number",
            suggestion="对照信用证核对：受益人抬头、金额与币种、货描、装运期、单据份数及措辞。",
        )]
    return []


def check_certificate_needs(model: OrderModel) -> list[CheckResult]:
    """R010 产地证/证书需求未记录：当前 OrderModel 没有证书需求字段，
    属于"信息从未被收集"，固定给一条 info 提醒人工确认。

    将来 OrderModel 增加证书字段后，本规则应改为只在该字段缺失时触发。
    """
    return [CheckResult(
        rule_id="R010",
        severity=Severity.INFO,
        message="产地证 / 证书需求未记录：订单中没有产地证（CO / Form A 等）"
                "和质保书（Mill Certificate）的需求信息。",
        field=None,
        suggestion="与客户确认是否需要产地证或材质证书；俄罗斯、中亚客户清关通常需要。",
    )]


# ── 规则注册表 ──────────────────────────────────────────────────

ALL_RULES = [
    check_seller_identity,    # R001
    check_buyer_identity,     # R002
    check_trade_terms,        # R003
    check_destination_port,   # R004
    check_unit_prices,        # R005
    check_quantities,         # R006
    check_weights,            # R007
    check_amounts,            # R008
    check_lc_manual_review,   # R009
    check_certificate_needs,  # R010
]
