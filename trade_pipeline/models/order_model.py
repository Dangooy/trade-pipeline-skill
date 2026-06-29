"""
models/order_model.py — OrderModel 全链路数据模型

OrderItem 含 item_uuid（uuid4 hex），用于 Excel 隐藏列锚点定位。
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class OrderRefs:
    seller_id: str
    buyer_id: str       # 不允许为 None
    terms_id: str


@dataclass
class OrderInfo:
    order_no: str
    format: str         # "standard" | "washers_mar"
    quote_no: str
    pi_number: str
    ci_number: str
    date: str
    currency: str       # "CNY" | "USD"
    price_unit: str     # "CNY/MPCS" | "USD/TON"
    bl_number: str | None = None
    lc_number: str | None = None
    vessel: str | None = None
    etd: str | None = None
    shipping_marks: str | None = None


@dataclass
class OrderItem:
    no: int
    item_uuid: str      # uuid4 hex，稳定唯一，写入 Excel 隐藏列
    part_no: str | None
    standard: str | None
    description_raw: str
    description: str
    quantity: float
    unit: str           # "pcs" | "kgs" | "tons"
    weight_kg: float | None = None
    barcode: str | None = None
    qty_box: int | None = None
    kg_mpcs: float | None = None
    group_key: str = ""
    din: str | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float = 1.0
    source_method: str = "excel"  # "excel" | "ocr" | "email" | ...
    # ── Packing fields (v1.1.0) — Gateway 收集，向后兼容 ──
    pcs_per_carton: int | None = None        # 每箱装多少件
    kg_per_carton_override: float | None = None  # 覆盖默认箱重
    weight_kg_per_piece: float | None = None  # 单件重量（kg/pc，比 kg_mpcs 更直观）

    @staticmethod
    def generate_uuid() -> str:
        return uuid.uuid4().hex[:12]


@dataclass
class DerivedData:
    total_items: int | None = None
    total_qty: float | None = None
    has_weight: bool | None = None
    exchange_rate: float | None = None
    port_of_loading: str | None = None
    port_of_destination: str | None = None
    pallet_count: int | None = None
    total_net_weight: float | None = None
    total_gross_weight: float | None = None
    total_measurement_m3: float | None = None
    total_cartons: int | None = None


@dataclass
class ResolvedEntities:
    seller: dict
    buyer: dict
    terms: dict
    bank: dict | None = None


@dataclass
class OrderMeta:
    source_files: list[str] = field(default_factory=list)
    created_at: str = ""
    last_modified: str = ""
    parser_model: str = ""
    parser_notes: str = ""
    review_status: str = "clean"
    review_file: str | None = None


@dataclass
class OrderModel:
    refs: OrderRefs
    order: OrderInfo
    items: list[OrderItem]
    derived: DerivedData = field(default_factory=DerivedData)
    meta: OrderMeta = field(default_factory=OrderMeta)
    confidence: dict[str, float] = field(default_factory=dict)
    resolved: ResolvedEntities | None = None  # 运行时填充，不持久化

    def to_json(self, path: str) -> None:
        self.meta.last_modified = datetime.now().isoformat()
        data = asdict(self)
        data.pop("resolved", None)  # 不持久化
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "OrderModel":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            refs=OrderRefs(**data["refs"]),
            order=OrderInfo(**data["order"]),
            items=[OrderItem(**item) for item in data["items"]],
            derived=DerivedData(**data.get("derived", {})),
            meta=OrderMeta(**data.get("meta", {})),
            confidence=data.get("confidence", {}),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("resolved", None)
        return data
