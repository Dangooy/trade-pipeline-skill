"""Tests for v1.1.0 PL Packing Gateway."""
import tempfile
from pathlib import Path

import yaml

from tests.conftest import SAMPLE_CONFIG, make_resolved_model
from trade_pipeline.validation.packing_review import (
    PackingReview, PackingReviewItem, PalletConfig,
    _normalize_key, apply_to_model, build_review_from_missing,
    lookup_from_catalog, review_path_for, save_to_catalog,
)
from trade_pipeline.writers.pl_writer_lite import (
    PLWriterLite,
)


# ── 数据结构 ────────────────────────────────────────────────────


def test_packing_review_json_roundtrip():
    """PackingReview can be serialized and read back."""
    review = PackingReview(
        order_no="TEST01",
        items=[
            PackingReviewItem(
                item_uuid="abc123",
                description="HEX BOLT M8x25",
                quantity=50000,
                unit="pcs",
                weight_kg_per_piece=0.0058,
                pcs_per_carton=1000,
                resolved=True,
                source="user",
            ),
        ],
        pallet=PalletConfig(preset="euro", length_mm=1200, width_mm=800,
                            cartons_per_pallet=36),
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        review.to_json(path)
        loaded = PackingReview.from_json(path)
        assert loaded.order_no == "TEST01"
        assert len(loaded.items) == 1
        assert loaded.items[0].weight_kg_per_piece == 0.0058
        assert loaded.pallet.preset == "euro"
        assert loaded.pallet.cartons_per_pallet == 36
        assert loaded.all_resolved() is True
    finally:
        Path(path).unlink(missing_ok=True)


def test_normalize_key_strips_and_lowercases():
    assert _normalize_key("  DIN 933 M8x25 ZP  ") == "din 933 m8x25 zp"
    assert _normalize_key("HEX  HEAD\tBOLT") == "hex head bolt"


def test_unresolved_count():
    review = PackingReview(
        order_no="X",
        items=[
            PackingReviewItem(item_uuid="a", description="x", quantity=1, unit="pcs", resolved=True),
            PackingReviewItem(item_uuid="b", description="y", quantity=1, unit="pcs", resolved=False),
            PackingReviewItem(item_uuid="c", description="z", quantity=1, unit="pcs", resolved=False),
        ],
    )
    assert review.unresolved_count() == 2
    assert review.all_resolved() is False


# ── product_catalog 自动学习 ──────────────────────────────────


def test_lookup_from_catalog_hit():
    config = {
        "product_catalog": {
            "hex bolt din 933 m8x25 zp": {
                "weight_kg_per_piece": 0.0058,
                "pcs_per_carton": 1000,
            }
        }
    }
    hit = lookup_from_catalog("HEX BOLT DIN 933 M8x25 ZP", config)
    assert hit is not None
    assert hit["weight_kg_per_piece"] == 0.0058


def test_lookup_from_catalog_miss():
    assert lookup_from_catalog("anything", {}) is None
    assert lookup_from_catalog("anything", {"product_catalog": {}}) is None


def test_save_to_catalog_writes_to_separate_file(tmp_path):
    """v1.1.0 修复 C8/C10：catalog 写到独立 product_catalog.yaml，不动 config.yaml。"""
    config_file = tmp_path / "config.yaml"
    # config.yaml 包含手工维护的内容和注释
    config_yaml_text = """# This is a hand-maintained comment
sellers:
  x:
    name: X  # important comment
"""
    config_file.write_text(config_yaml_text, encoding="utf-8")
    config_original_text = config_file.read_text(encoding="utf-8")

    ok = save_to_catalog(
        "HEX NUT M8",
        {"weight_kg_per_piece": 0.0028, "pcs_per_carton": 5000},
        config_file,
    )
    assert ok is True
    # config.yaml 完全没动（注释保留）
    assert config_file.read_text(encoding="utf-8") == config_original_text
    # catalog 写到 product_catalog.yaml
    catalog_file = tmp_path / "product_catalog.yaml"
    assert catalog_file.exists()
    catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
    assert "hex nut m8" in catalog
    assert catalog["hex nut m8"]["pcs_per_carton"] == 5000


def test_save_to_catalog_atomic(tmp_path):
    """v1.1.0 修复 C10：catalog 写入是原子的，断电不会损坏文件。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("sellers: {}\n", encoding="utf-8")
    # 先写一次
    save_to_catalog("ITEM A", {"weight_kg_per_piece": 1.0}, config_file)
    # 写入过程中临时文件不应残留
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
    # catalog 文件存在且可读
    catalog_file = tmp_path / "product_catalog.yaml"
    assert catalog_file.exists()
    catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
    assert "item a" in catalog


# ── apply_to_model ─────────────────────────────────────────────


def test_apply_to_model_writes_weights():
    """apply 后 OrderItem 应有 weight_kg 和 weight_kg_per_piece。"""
    model = make_resolved_model(with_weights=False)  # 无 weight
    review = PackingReview(
        order_no=model.order.order_no,
        items=[
            PackingReviewItem(
                item_uuid=model.items[0].item_uuid,
                description=model.items[0].description,
                quantity=model.items[0].quantity,
                unit=model.items[0].unit,
                weight_kg_per_piece=0.0058,
                pcs_per_carton=1000,
                resolved=True,
                source="user",
            ),
            PackingReviewItem(
                item_uuid=model.items[1].item_uuid,
                description=model.items[1].description,
                quantity=model.items[1].quantity,
                unit=model.items[1].unit,
                kg_per_1000pcs=2.8,
                pcs_per_carton=5000,
                resolved=True,
                source="user",
            ),
        ],
    )
    res = apply_to_model(model, review)
    assert res["applied"] == 2
    assert model.items[0].weight_kg_per_piece == 0.0058
    assert model.items[0].weight_kg == round(0.0058 * 50000, 3)
    assert model.items[0].pcs_per_carton == 1000
    # 千件路径
    assert model.items[1].kg_mpcs == 2.8
    assert model.items[1].weight_kg == round(2.8 * 100000 / 1000, 3)


def test_apply_skips_unresolved():
    model = make_resolved_model(with_weights=False)
    review = PackingReview(
        order_no=model.order.order_no,
        items=[
            PackingReviewItem(
                item_uuid=model.items[0].item_uuid,
                description=model.items[0].description,
                quantity=model.items[0].quantity,
                unit=model.items[0].unit,
                resolved=False,  # 未填写
            ),
        ],
    )
    res = apply_to_model(model, review)
    assert res["applied"] == 0
    assert res["still_pending"] == 1
    assert model.items[0].weight_kg is None


def test_apply_writes_to_catalog(tmp_path):
    """resolved + source='user' 的条目会被 save_to_catalog 写回。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"product_catalog": {}}, allow_unicode=True),
                            encoding="utf-8")
    model = make_resolved_model(with_weights=False)
    review = PackingReview(
        order_no=model.order.order_no,
        items=[
            PackingReviewItem(
                item_uuid=model.items[0].item_uuid,
                description=model.items[0].description,
                quantity=model.items[0].quantity,
                unit=model.items[0].unit,
                weight_kg_per_piece=0.0058,
                pcs_per_carton=1000,
                resolved=True,
                source="user",
            ),
        ],
    )
    res = apply_to_model(
        model, review, config={"product_catalog": {}},
        save_new_to_catalog=True, config_path=config_file,
    )
    assert res["saved_to_catalog"] == 1
    # v1.1.0: catalog 写到独立文件
    catalog_file = tmp_path / "product_catalog.yaml"
    assert catalog_file.exists()
    catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
    key = _normalize_key(model.items[0].description)
    assert key in catalog


# ── build_review_from_missing + catalog 联动 ───────────────────


def test_build_review_auto_fills_from_catalog():
    """build_review 时已在 catalog 中的条目应自动 resolved=True。"""
    model = make_resolved_model(with_weights=False)
    config = {
        "product_catalog": {
            _normalize_key(model.items[0].description): {
                "weight_kg_per_piece": 0.0058,
                "pcs_per_carton": 1000,
            }
        }
    }
    review = build_review_from_missing(model, model.items, config)
    assert len(review.items) == 2
    # item[0] 命中 catalog
    assert review.items[0].resolved is True
    assert review.items[0].source == "catalog"
    assert review.items[0].weight_kg_per_piece == 0.0058
    # item[1] 未命中
    assert review.items[1].resolved is False


# ── PLWriter 联动 PackingReview ─────────────────────────────────


def test_pl_writes_with_review_pallet_config():
    """传入 packing_review 后，PL 使用其 pallet 配置（cartons_per_pallet）。"""
    model = make_resolved_model(with_weights=True)
    review = PackingReview(
        order_no=model.order.order_no,
        items=[],  # 模型已有 weight，items 可空
        pallet=PalletConfig(preset="us", cartons_per_pallet=48,
                            self_weight_kg=35.0),
    )
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        result = PLWriterLite(model, SAMPLE_CONFIG).write(path, packing_review=review)
        assert result["success"] is True
        # 默认 36 vs review 给的 48 → review 应该生效
        # 用反推方式验证：total_pallets = ceil(total_cartons / 48)
        import math
        expected_pallets = max(1, math.ceil(result["total_cartons"] / 48))
        assert result["total_pallets"] == expected_pallets
    finally:
        Path(path).unlink(missing_ok=True)


def test_pl_works_with_pcs_per_carton_override():
    """OrderItem.pcs_per_carton 应该让箱数按"件数 / 每箱件数"算。"""
    model = make_resolved_model(with_weights=True)
    # 强制 item[0] 用 pcs_per_carton = 1000，qty=50000 → 应该 50 箱
    model.items[0].pcs_per_carton = 1000
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        result = PLWriterLite(model, SAMPLE_CONFIG).write(path)
        assert result["success"] is True
        # 总箱数应该 >= 50（item[0] 自己就 50 箱）
        assert result["total_cartons"] >= 50
    finally:
        Path(path).unlink(missing_ok=True)


# ── review_path_for ─────────────────────────────────────────────


def test_review_path_for():
    p = review_path_for("/tmp/output", "ORD123")
    assert p.name == "ORD123_packing_review.json"
    assert "output" in str(p) or "tmp" in str(p)


# ── 校验链测试 (C6, C7, C12) ────────────────────────────────────


def test_from_json_rejects_wrong_order_no(tmp_path):
    """C6 修复：传错订单的 review.json 应该被拒绝。"""
    import pytest
    from trade_pipeline.validation.packing_review import ReviewMismatchError
    review = PackingReview(order_no="ORDER_A", items=[])
    path = tmp_path / "review.json"
    review.to_json(str(path))
    with pytest.raises(ReviewMismatchError):
        PackingReview.from_json(str(path), expected_order_no="ORDER_B")


def test_from_json_ignores_unknown_fields(tmp_path):
    """C12 修复：未来加字段时旧版本能容错读取。"""
    import json
    forward_compat = {
        "order_no": "FUTURE_ORDER",
        "items": [{
            "item_uuid": "x", "description": "y", "quantity": 1, "unit": "pcs",
            "resolved": True,
            "future_field_v2": "ignored",  # 旧版本不认识
        }],
        "pallet": {"preset": "euro", "height_mm": 144},  # height_mm 是未来字段
        "version": "v2",
    }
    path = tmp_path / "review.json"
    path.write_text(json.dumps(forward_compat), encoding="utf-8")
    # 不应该抛 TypeError
    review = PackingReview.from_json(str(path))
    assert review.order_no == "FUTURE_ORDER"
    assert len(review.items) == 1


def test_from_json_rejects_wrong_schema(tmp_path):
    """C12: 完全错的 JSON shape 应该抛 ReviewSchemaError。"""
    import json
    import pytest
    from trade_pipeline.validation.packing_review import ReviewSchemaError
    path = tmp_path / "wrong.json"
    # 这是 buyer review.json 的格式，没有 items 顶层字段
    path.write_text(json.dumps({"buyer_id": "x", "candidates": []}), encoding="utf-8")
    with pytest.raises(ReviewSchemaError):
        PackingReview.from_json(str(path))


# ── falsy/None 陷阱测试 (C3, C4) ───────────────────────────────


def test_check_completeness_allows_zero_weight():
    """C4 修复：weight_kg=0.0 应该被视为已提供，不报 missing。"""
    from trade_pipeline.writers.pl_writer_lite import _check_weight_completeness
    model = make_resolved_model(with_weights=False)
    # 给一个 item 显式 weight_kg=0（赠品/试样）
    model.items[0].weight_kg = 0.0
    missing = _check_weight_completeness(model.items)
    # 只有 item[1] 缺，item[0] 显式 0 不算缺
    assert len(missing) == 1
    assert missing[0] is model.items[1]


# ── 重复 (desc, qty) 测试 (C19) ────────────────────────────────


def test_apply_handles_duplicate_desc_qty():
    """C19 修复：两行同 description 同 quantity 时 review 应能分别填到两行。"""
    model = make_resolved_model(with_weights=False)
    # 把 item[1] 改成和 item[0] 一样的 description + quantity
    # 但 UUID 不同
    model.items[1].description = model.items[0].description
    model.items[1].quantity = model.items[0].quantity

    review = PackingReview(
        order_no=model.order.order_no,
        items=[
            # 用一个 UUID 不匹配的项触发 desc_qty fallback
            PackingReviewItem(
                item_uuid="fake_uuid_1",
                description=model.items[0].description,
                quantity=model.items[0].quantity,
                unit=model.items[0].unit,
                weight_kg_per_piece=0.01,
                resolved=True,
            ),
            PackingReviewItem(
                item_uuid="fake_uuid_2",
                description=model.items[0].description,
                quantity=model.items[0].quantity,
                unit=model.items[0].unit,
                weight_kg_per_piece=0.02,
                resolved=True,
            ),
        ],
    )
    res = apply_to_model(model, review)
    # 两个 item 都应该被填到（分别匹配两个 model item）
    assert res["matched_by"]["desc_qty"] == 2
    assert res["applied"] == 2
    assert model.items[0].weight_kg_per_piece is not None
    assert model.items[1].weight_kg_per_piece is not None
    # 而且分别拿到不同的值
    assert model.items[0].weight_kg_per_piece != model.items[1].weight_kg_per_piece


# ── 全角空格测试 (C9) ──────────────────────────────────────────


def test_normalize_handles_fullwidth_space():
    """C9 修复：中文全角空格应该被规整化为半角空格。"""
    full_width = "HEX　BOLT　DIN 933"  # 全角空格 U+3000
    half_width = "HEX BOLT DIN 933"
    assert _normalize_key(full_width) == _normalize_key(half_width)


def test_normalize_handles_nbsp():
    """C9 修复：不间断空格也应该被规整化。"""
    nbsp = "HEX\xa0BOLT"  # NO-BREAK SPACE
    half = "HEX BOLT"
    assert _normalize_key(nbsp) == _normalize_key(half)
