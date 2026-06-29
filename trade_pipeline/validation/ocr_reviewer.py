"""
validation/ocr_reviewer.py — OCR 来源关键字段逐行确认器

OCR/图片/扫描来源不得只做低置信提示。
对 source_method 为 "ocr" 或 "image" 的 item，关键字段必须全量逐行确认。
即使 confidence=0.99 的 OCR 字段也必须逐行确认。
"""
from trade_pipeline.validation.manual_completion import ReviewItem

# 默认必须确认的关键字段
DEFAULT_FORCE_FIELDS = [
    "description",
    "standard",
    "quantity",
    "unit",
    "weight_kg",
]

# OCR 来源标识
OCR_SOURCE_METHODS = ("ocr", "image")


def review_ocr_items(model, config: dict | None = None) -> list[ReviewItem]:
    """
    对 OCR 来源的 item，关键字段全量逐行生成 ReviewItem。

    规则：
      - source_method 为 "ocr" 或 "image" 的 item → 全部关键字段生成 ReviewItem
      - 不只是低置信提示，而是强制逐行 review
      - 关键字段列表由 config["ocr_review"]["force_review_fields"] 控制

    参数:
        model: OrderModel 实例
        config: 可选，含 ocr_review 配置段

    返回:
        list[ReviewItem] — 需要人工确认的条目
    """
    ocr_cfg = (config or {}).get("ocr_review", {})
    force_fields = ocr_cfg.get("force_review_fields", DEFAULT_FORCE_FIELDS)

    reviews = []
    for i, item in enumerate(model.items):
        if item.source_method not in OCR_SOURCE_METHODS:
            continue

        for field_name in force_fields:
            val = getattr(item, field_name, None)
            reviews.append(ReviewItem(
                field_path=f"items[{i}].{field_name}",
                current_value=val,
                candidate_values=[val] if val is not None else [],
                confidence=item.confidence,
                source="ocr",
                reason=f"OCR 来源关键字段必须人工确认 (source_method={item.source_method})",
                required_action="confirm",
            ))

    return reviews


def has_ocr_items(model) -> bool:
    """检查 model 中是否有 OCR 来源的 item"""
    return any(
        item.source_method in OCR_SOURCE_METHODS
        for item in model.items
    )
