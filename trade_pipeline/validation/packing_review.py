"""
validation/packing_review.py — PL 装箱信息 Gateway

当询价单缺重量信息时，PLWriterLite 抛 PackingInfoMissingError。
本模块负责：
  1. 把缺失项写成 review.json 文件（CLI 模式）
  2. 给 GUI 提供同样的数据结构（GUI 模式）
  3. 收完信息后 apply 回 OrderModel
  4. 与 product_catalog 自动学习联动

复用 v1.0.3 的 PackingInfoMissingError 机制，不发明新机制。
"""
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from trade_pipeline.models.order_model import OrderModel, OrderItem


# ── 异常 ────────────────────────────────────────────────────────


class ReviewSchemaError(ValueError):
    """Raised when a JSON file does not match the PackingReview schema."""


class ReviewMismatchError(ValueError):
    """Raised when --confirm-packing review.json's order_no doesn't match."""


# ── 数据结构 ────────────────────────────────────────────────────


@dataclass
class PackingReviewItem:
    """单个 item 的包装信息（Gateway L1：产品维度）"""
    item_uuid: str           # 锚点定位（不靠行号）
    description: str         # 给用户看
    quantity: float          # 给用户看
    unit: str                # "pcs" | "kgs" | ...
    # 用户填写：
    weight_kg_per_piece: float | None = None    # 单件重量 kg/pc
    kg_per_1000pcs: float | None = None         # 或千件重量 kg/MPCS
    pcs_per_carton: int | None = None           # 每箱装多少
    kg_per_carton: float | None = None          # 或每箱装多少 kg
    # 标记
    resolved: bool = False
    source: str = "user"     # "user" | "catalog" | "auto"


@dataclass
class PalletConfig:
    """订单层托盘配置（Gateway L2 + L3）"""
    preset: str = "euro"           # pallet_presets 的 key
    length_mm: int | None = None   # 自定义时直接填
    width_mm: int | None = None
    self_weight_kg: float = 28.0
    cartons_per_pallet: int = 36   # L2 直接填或 L3 反推


@dataclass
class PackingReview:
    """订单层 PL Review 文件根结构"""
    order_no: str
    items: list[PackingReviewItem] = field(default_factory=list)
    pallet: PalletConfig = field(default_factory=PalletConfig)
    version: str = "v1"

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, path: str, expected_order_no: str | None = None) -> "PackingReview":
        """Load a PackingReview from JSON.

        Forward/backward compat: unknown keys in items/pallet are silently
        dropped (instead of raising TypeError), so future schema additions
        don't break older versions of trade-pipeline.

        If expected_order_no is provided and doesn't match the file's order_no,
        raises ReviewMismatchError to prevent accidentally applying review from
        a different order.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or "order_no" not in data or "items" not in data:
            raise ReviewSchemaError(
                f"{path} does not look like a packing_review.json "
                f"(missing 'order_no' or 'items')."
            )

        file_order_no = data["order_no"]
        if expected_order_no is not None and file_order_no != expected_order_no:
            raise ReviewMismatchError(
                f"Packing review order_no='{file_order_no}' does not match "
                f"current order='{expected_order_no}'. Refusing to apply."
            )

        item_fields = {f.name for f in PackingReviewItem.__dataclass_fields__.values()}
        pallet_fields = {f.name for f in PalletConfig.__dataclass_fields__.values()}

        items = []
        for it in data.get("items", []):
            if not isinstance(it, dict):
                continue
            kwargs = {k: v for k, v in it.items() if k in item_fields}
            try:
                items.append(PackingReviewItem(**kwargs))
            except TypeError as e:
                raise ReviewSchemaError(
                    f"Invalid packing_review item in {path}: {e}. Got: {it}"
                ) from e

        pallet_data = data.get("pallet") or {}
        pallet_kwargs = {k: v for k, v in pallet_data.items() if k in pallet_fields}
        pallet = PalletConfig(**pallet_kwargs)

        return cls(
            order_no=file_order_no,
            items=items,
            pallet=pallet,
            version=data.get("version", "v1"),
        )

    def all_resolved(self) -> bool:
        return all(it.resolved for it in self.items)

    def unresolved_count(self) -> int:
        return sum(1 for it in self.items if not it.resolved)


# ── product_catalog 自动学习 ──────────────────────────────────


_NORM_RE = re.compile(r"\s+")
# 全角空格 / 各种 Unicode 空白先转 ASCII 空格，再让 _NORM_RE 折叠
_FULLWIDTH_SPACE_RE = re.compile(r"[　  -​  ]")


def _normalize_key(description: str) -> str:
    """canonical description → catalog lookup key（小写，去多余空格）

    v1.1.0 修复 C9：先把全角空格 U+3000、不间断空格 U+00A0、各种 thin space
    都替换为半角空格，再让 \\s+ 折叠。
    """
    s = _FULLWIDTH_SPACE_RE.sub(" ", description)
    return _NORM_RE.sub(" ", s.strip().lower())


def _catalog_path(config_or_path) -> Path:
    """v1.1.0 修复 C8/C10：产品库写到独立 product_catalog.yaml，不动 config.yaml。

    catalog 文件总是与 config.yaml 同目录。
    """
    if isinstance(config_or_path, (str, Path)):
        return Path(config_or_path).parent / "product_catalog.yaml"
    return Path("product_catalog.yaml")  # fallback for in-memory only


def _load_catalog_file(catalog_path: Path) -> dict:
    """从独立 catalog 文件读，文件不存在或为空返回 {}。"""
    if not catalog_path.exists():
        return {}
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def lookup_from_catalog(description: str, config: dict) -> dict | None:
    """命中返回字典；未命中返回 None。

    v1.1.0：先查 config['product_catalog']（已合并），再查独立的 product_catalog.yaml。
    """
    key = _normalize_key(description)
    # 兼容：仍支持 config 内嵌的 product_catalog
    catalog = config.get("product_catalog") or {}
    if key in catalog:
        return catalog[key]
    # 也查独立文件（如果 config 里有路径线索就不查；否则跳过）
    return None


def save_to_catalog(
    description: str,
    packing_info: dict,
    config_path: str | Path,
) -> bool:
    """把 Gateway 收到的 packing_info 写到 product_catalog.yaml（独立文件）。

    v1.1.0 修复 C8 + C10：
    - 不再写 config.yaml（保留其注释和格式）
    - 写独立 product_catalog.yaml
    - 使用 temp-file + rename 保证原子性（断电/Ctrl-C 不会损坏文件）
    """
    catalog_path = _catalog_path(config_path)
    catalog = _load_catalog_file(catalog_path)
    key = _normalize_key(description)
    catalog[key] = packing_info

    # 原子写入：先写临时文件，再 rename 替换
    tmp_path = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                catalog, f, allow_unicode=True, sort_keys=False,
                default_flow_style=False,
            )
        # POSIX rename 是原子的；Windows os.replace 也是原子的
        import os
        os.replace(tmp_path, catalog_path)
        return True
    except Exception:
        # 清理临时文件
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


# ── 构造 / 应用 ─────────────────────────────────────────────────


def build_review_from_missing(
    order: OrderModel,
    missing_items: list[OrderItem],
    config: dict,
) -> PackingReview:
    """根据 PackingInfoMissingError 的 missing_items 列表构造 PackingReview。

    自动用 product_catalog 预填能命中的条目（resolved=True）。
    """
    review = PackingReview(order_no=order.order.order_no)

    # 默认 pallet 用 config.packing 的现有值
    packing_cfg = (config or {}).get("packing", {})
    review.pallet.self_weight_kg = packing_cfg.get("pallet_self_weight_kg", 28.0)
    review.pallet.cartons_per_pallet = packing_cfg.get("cartons_per_pallet", 36)
    # 默认欧标尺寸
    presets = (config or {}).get("pallet_presets", {})
    euro = presets.get("euro", {})
    review.pallet.length_mm = euro.get("length_mm", 1200)
    review.pallet.width_mm = euro.get("width_mm", 800)

    for item in missing_items:
        ri = PackingReviewItem(
            item_uuid=item.item_uuid,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
        )
        # 尝试从 catalog 自动填
        hit = lookup_from_catalog(item.description, config)
        if hit:
            ri.weight_kg_per_piece = hit.get("weight_kg_per_piece")
            ri.kg_per_1000pcs = hit.get("kg_per_1000pcs")
            ri.pcs_per_carton = hit.get("pcs_per_carton")
            ri.kg_per_carton = hit.get("default_carton_weight_kg")
            ri.source = "catalog"
            ri.resolved = True  # catalog 命中视为已填
        review.items.append(ri)

    return review


def apply_to_model(
    model: OrderModel,
    review: PackingReview,
    config: dict | None = None,
    save_new_to_catalog: bool = False,
    config_path: str | Path | None = None,
) -> dict:
    """把 PackingReview 应用回 OrderModel：
      - 用 item_uuid 锚点匹配，回填 weight_kg / kg_mpcs / pcs_per_carton 等
      - UUID 不匹配时，降级用 (description, no) 匹配（处理重新解析询价单的场景）
      - 把 review.pallet 写到 model.derived（pallet_count 留给 Writer 算）

    可选：把 source='user' 的条目写回 product_catalog（自动学习）。

    返回：{"applied": N, "still_pending": M, "saved_to_catalog": K, "matched_by": dict}
    """
    by_uuid = {it.item_uuid: it for it in model.items}

    # Fallback by (description, quantity) — must handle duplicates and int/float mismatch.
    # 用 list-of-tuples 而非 dict，以支持同 description 同 quantity 多行；
    # 用 float(quantity) 归一化避免 JSON roundtrip 把 50000 变成 50000.0 的匹配失败。
    def _qty_key(q):
        try:
            return float(q)
        except (TypeError, ValueError):
            return q

    desc_qty_index: dict[tuple, list] = {}
    for it in model.items:
        key = (it.description, _qty_key(it.quantity))
        desc_qty_index.setdefault(key, []).append(it)
    # 标记哪些 model item 已经被某 review item 配上，避免一份 review 同时填两行
    used_model_items: set[int] = set()

    applied = 0
    overwritten = 0  # 覆盖已有 weight_kg 的次数
    saved_to_catalog = 0
    matched_by = {"uuid": 0, "desc_qty": 0, "missed": 0}

    for ri in review.items:
        if not ri.resolved:
            continue
        target = by_uuid.get(ri.item_uuid)
        if target is not None and id(target) not in used_model_items:
            matched_by["uuid"] += 1
        else:
            # Fallback: match by (description, quantity) — 不使用已配过的 model item
            target = None
            candidates = desc_qty_index.get((ri.description, _qty_key(ri.quantity)), [])
            for cand in candidates:
                if id(cand) not in used_model_items:
                    target = cand
                    break
            if target is not None:
                matched_by["desc_qty"] += 1
            else:
                matched_by["missed"] += 1
                continue

        used_model_items.add(id(target))

        # 写回 weight 字段（优先级：用户填的 piece > 1000pcs）
        # 记录是否覆盖了已有 weight_kg（让上层能警告）
        pre_existing_weight = target.weight_kg

        if ri.weight_kg_per_piece is not None:
            target.weight_kg_per_piece = ri.weight_kg_per_piece
            # 同步算 weight_kg 总重（kg）
            target.weight_kg = round(ri.weight_kg_per_piece * target.quantity, 3)
        elif ri.kg_per_1000pcs is not None:
            target.kg_mpcs = ri.kg_per_1000pcs
            target.weight_kg = round(ri.kg_per_1000pcs * target.quantity / 1000, 3)

        # 检查覆盖：如果原 weight_kg 与新值差异大于 1%，记为覆盖
        if (pre_existing_weight is not None and target.weight_kg is not None
                and pre_existing_weight > 0
                and abs(target.weight_kg - pre_existing_weight) / pre_existing_weight > 0.01):
            overwritten += 1

        if ri.pcs_per_carton is not None:
            target.pcs_per_carton = ri.pcs_per_carton
        if ri.kg_per_carton is not None:
            target.kg_per_carton_override = ri.kg_per_carton

        applied += 1

        # 自动学习：用户填的写回 catalog
        if save_new_to_catalog and ri.source == "user" and config_path:
            cfg = config or {}
            packing_info = {
                k: v for k, v in {
                    "weight_kg_per_piece": ri.weight_kg_per_piece,
                    "kg_per_1000pcs": ri.kg_per_1000pcs,
                    "pcs_per_carton": ri.pcs_per_carton,
                    "default_carton_weight_kg": ri.kg_per_carton,
                }.items() if v is not None
            }
            if packing_info and save_to_catalog(target.description, packing_info, config_path):
                saved_to_catalog += 1
                # 同步内存 config，便于后续 lookup
                if "product_catalog" not in cfg:
                    cfg["product_catalog"] = {}
                cfg["product_catalog"][_normalize_key(target.description)] = packing_info

    # 把 pallet 配置写到 derived（供 PLWriter 使用）
    if model.derived is None:
        from trade_pipeline.models.order_model import DerivedData
        model.derived = DerivedData()
    if review.pallet.cartons_per_pallet:
        # 不直接写 pallet_count（要等 Writer 算总箱数才知道）；
        # 写一个临时字段供 Writer 读取
        pass  # PLWriter 会从 review.pallet 直接读

    return {
        "applied": applied,
        "still_pending": review.unresolved_count(),
        "saved_to_catalog": saved_to_catalog,
        "matched_by": matched_by,
        "overwritten": overwritten,
    }


# ── 文件命名规范 ────────────────────────────────────────────────


def review_path_for(output_dir: str | Path, order_no: str) -> Path:
    """{output_dir}/{order_no}_packing_review.json"""
    return Path(output_dir) / f"{order_no}_packing_review.json"
