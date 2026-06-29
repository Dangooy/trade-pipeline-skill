"""
validation/manual_completion.py — review.json 生成与回写机制

当出现以下情况时生成 review.json：
  - buyer 匹配失败
  - OCR 关键字段待确认
  - 低置信关键字段
  - 必填字段缺失
  - 多 source 冲突

运行机制：
  1. 第一次运行：生成 {order_no}_review.json，pipeline 中止
  2. 人工编辑 review.json（填 resolved_value，设 resolved: true）
  3. 第二次运行：--confirm review.json → apply_review() 回写 model
"""
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


class NeedsReview(Exception):
    """pipeline 软阻断：需要人工确认"""
    def __init__(self, review_path: str, pending_count: int):
        self.review_path = review_path
        self.pending_count = pending_count
        super().__init__(
            f"需要人工确认 {pending_count} 项，review 文件: {review_path}"
        )


@dataclass
class ReviewItem:
    """review.json 中的单个待确认项"""
    field_path: str             # "refs.buyer_id" 或 "items[3].quantity"
    current_value: Any          # 当前值（可能是 None）
    candidate_values: list      # 候选值列表
    confidence: float           # 0.0-1.0
    source: str                 # "llm" | "ocr" | "excel" | "user" | "matcher"
    reason: str                 # 需要确认的原因
    required_action: str        # "select" | "confirm" | "fill"
    resolved: bool = False      # 人工处理后设为 True
    resolved_value: Any = None  # 人工填入的最终值


@dataclass
class ReviewFile:
    """完整的 review.json 数据结构"""
    order_no: str
    created_at: str
    items: list[ReviewItem]
    status: str = "pending"     # "pending" | "resolved"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str) -> str:
        """写入 review.json，返回路径"""
        data = self.to_dict()
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    @classmethod
    def from_json(cls, path: str) -> "ReviewFile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            order_no=data["order_no"],
            created_at=data["created_at"],
            items=[ReviewItem(**item) for item in data["items"]],
            status=data.get("status", "pending"),
        )

    @property
    def pending_count(self) -> int:
        return sum(1 for item in self.items if not item.resolved)

    @property
    def is_fully_resolved(self) -> bool:
        return all(item.resolved for item in self.items)


def generate_review(order_no: str, review_items: list[ReviewItem],
                    out_dir: str) -> str:
    """
    生成 review.json 文件。

    参数:
        order_no: 订单号
        review_items: 需要人工确认的项目列表
        out_dir: 输出目录

    返回:
        review.json 文件路径
    """
    review = ReviewFile(
        order_no=order_no,
        created_at=datetime.now().isoformat(),
        items=review_items,
        status="pending",
    )
    out_path = str(Path(out_dir) / f"{order_no}_review.json")
    review.to_json(out_path)
    return out_path


def _resolve_field_path(path: str):
    """
    解析 field_path 为 (obj_path_parts, final_key) 元组。
    支持格式:
      "refs.buyer_id"         → (["refs"], "buyer_id")
      "items[3].quantity"     → (["items", 3], "quantity")
      "order.bl_number"       → (["order"], "bl_number")
      "derived.port_of_dest"  → (["derived"], "port_of_dest")
    """
    import re
    parts = []
    for segment in path.split("."):
        m = re.match(r'^(\w+)\[(\d+)\]$', segment)
        if m:
            parts.append(m.group(1))
            parts.append(int(m.group(2)))
        else:
            parts.append(segment)
    return parts[:-1], parts[-1]


def _get_nested(obj, path_parts):
    """按路径获取嵌套对象"""
    current = obj
    for part in path_parts:
        if isinstance(part, int):
            current = current[part]
        elif isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)
    return current


def _set_nested(obj, path_parts, key, value):
    """按路径设置嵌套对象的属性"""
    target = _get_nested(obj, path_parts)
    if isinstance(target, dict):
        target[key] = value
    else:
        setattr(target, key, value)


def apply_review(model, review_path: str) -> dict:
    """
    从已编辑的 review.json 读取 resolved_value，回写到 OrderModel。

    参数:
        model: OrderModel 实例
        review_path: review.json 路径

    返回:
        {"applied": N, "still_pending": N, "errors": [...]}

    要求:
        review.json 中 resolved=True 的项必须有 resolved_value。
    """
    review = ReviewFile.from_json(review_path)
    applied = 0
    still_pending = 0
    errors = []

    for item in review.items:
        if not item.resolved:
            still_pending += 1
            continue

        if item.resolved_value is None and item.required_action == "fill":
            errors.append(
                f"{item.field_path}: resolved=True 但 resolved_value 为 None"
            )
            continue

        try:
            path_parts, final_key = _resolve_field_path(item.field_path)
            _set_nested(model, path_parts, final_key, item.resolved_value)
            applied += 1
        except (AttributeError, IndexError, KeyError) as e:
            errors.append(f"{item.field_path}: 回写失败 — {e}")

    # 更新 meta
    if still_pending == 0:
        model.meta.review_status = "reviewed"
    else:
        model.meta.review_status = "pending_review"
    model.meta.review_file = review_path

    return {"applied": applied, "still_pending": still_pending, "errors": errors}


def gate(model, review_items: list[ReviewItem], out_dir: str):
    """
    验证门控：有待确认项 → 写 review.json + raise NeedsReview
    无待确认项 → 直接通过，返回 model

    参数:
        model: OrderModel
        review_items: 收集到的所有 ReviewItem
        out_dir: 输出目录

    返回:
        model（无阻断时）

    抛出:
        NeedsReview（有待确认项时）
    """
    if not review_items:
        model.meta.review_status = "clean"
        return model

    review_path = generate_review(model.order.order_no, review_items, out_dir)
    model.meta.review_status = "pending_review"
    model.meta.review_file = review_path
    raise NeedsReview(review_path, len(review_items))
