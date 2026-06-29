"""
tests/test_resolve_entities.py — Codex review 二轮 P1#2 回归

确保 pipeline 末端的安全网工作：seller 在 config 中缺失时必须抛 EntityResolutionError，
而非 fail-silent 让用户拿到卖方信息为空的单据。
"""
import pytest

from trade_pipeline.models.order_model import (
    DerivedData, OrderInfo, OrderMeta, OrderModel, OrderRefs,
)
from trade_pipeline.understanding.assembler import (
    EntityResolutionError, resolve_entities,
)


def _make_model(seller_id: str = "acme", buyer_id: str = "gf",
                terms_id: str = "standard_cny") -> OrderModel:
    """构造一个最小可用的 OrderModel，仅 refs 字段对测试有意义。"""
    return OrderModel(
        refs=OrderRefs(seller_id=seller_id, buyer_id=buyer_id, terms_id=terms_id),
        order=OrderInfo(
            order_no="T01", format="standard", quote_no="QT-T01",
            pi_number="PI-T01", ci_number="CI-T01", date="01 January 2026",
            currency="CNY", price_unit="CNY/MPCS",
        ),
        items=[],
        derived=DerivedData(total_items=0, total_qty=0, has_weight=False),
        meta=OrderMeta(
            source_files=[], created_at="2026-01-01T00:00:00",
            last_modified="2026-01-01T00:00:00",
            parser_model="rules", review_status="clean",
        ),
    )


class TestResolveEntitiesHardCheck:
    """seller 必须存在；其他实体可 fallback 到空。"""

    def test_valid_seller_passes(self):
        config = {
            "sellers": {"acme": {"name_en": "ACME Co"}},
            "buyers": {"gf": {"name_en": "GF"}},
            "terms_templates": {"standard_cny": {"payment": "30/70"}},
        }
        model = _make_model("acme", "gf", "standard_cny")
        result = resolve_entities(model, config)
        assert result.resolved.seller["name_en"] == "ACME Co"

    def test_missing_seller_raises(self):
        config = {
            "sellers": {"other": {"name_en": "Other Co"}},
            "buyers": {"gf": {"name_en": "GF"}},
        }
        model = _make_model("acme", "gf")
        with pytest.raises(EntityResolutionError) as exc_info:
            resolve_entities(model, config)
        err = exc_info.value
        assert err.entity_type == "seller"
        assert err.entity_id == "acme"
        assert "other" in err.available_ids

    def test_empty_sellers_section_raises(self):
        """sellers 段存在但是空 dict 时也应抛错。"""
        config = {"sellers": {}, "buyers": {}}
        model = _make_model("acme")
        with pytest.raises(EntityResolutionError):
            resolve_entities(model, config)

    def test_missing_sellers_section_raises(self):
        """config 完全没有 sellers 段（或为 None）时也应抛错，不要 fail-silent。"""
        config = {"buyers": {}}
        model = _make_model("acme")
        with pytest.raises(EntityResolutionError) as exc_info:
            resolve_entities(model, config)
        assert exc_info.value.available_ids == []

    def test_sellers_is_none_raises(self):
        """yaml 解析后 sellers 是 None（而不是缺失）时也走 fallback 到空。"""
        config = {"sellers": None, "buyers": {}}
        model = _make_model("acme")
        with pytest.raises(EntityResolutionError):
            resolve_entities(model, config)

    def test_missing_buyer_does_not_raise(self):
        """buyer 缺失允许 fallback 到空（已在 buyer_matcher 上游处理过）。"""
        config = {
            "sellers": {"acme": {"name_en": "ACME"}},
            "buyers": {},
        }
        model = _make_model("acme", "ghost_buyer")
        result = resolve_entities(model, config)
        assert result.resolved.buyer == {}
        assert result.resolved.seller["name_en"] == "ACME"

    def test_missing_terms_does_not_raise(self):
        """terms 缺失允许 fallback 到空（下游 Writer 容忍空字符串）。"""
        config = {
            "sellers": {"acme": {"name_en": "ACME"}},
            "buyers": {"gf": {"name_en": "GF"}},
        }
        model = _make_model("acme", "gf", "ghost_terms")
        result = resolve_entities(model, config)
        assert result.resolved.terms == {}


class TestEntityResolutionErrorMessage:
    """错误信息必须引导用户去配置中心修复。"""

    def test_message_lists_available_sellers(self):
        config = {"sellers": {"acme": {}, "delta": {}}, "buyers": {}}
        model = _make_model("ghost")
        with pytest.raises(EntityResolutionError) as exc_info:
            resolve_entities(model, config)
        msg = str(exc_info.value)
        assert "ghost" in msg
        assert "acme" in msg
        assert "delta" in msg
        assert "配置中心" in msg

    def test_message_handles_no_sellers(self):
        config = {"sellers": {}, "buyers": {}}
        model = _make_model("ghost")
        with pytest.raises(EntityResolutionError) as exc_info:
            resolve_entities(model, config)
        msg = str(exc_info.value)
        assert "ghost" in msg
        # 应该包含"无"或类似提示
        assert "无" in msg or "(" in msg
