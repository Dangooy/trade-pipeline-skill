"""Tests for OrderModel serialization/deserialization."""
import tempfile
from pathlib import Path

from trade_pipeline.models.order_model import (
    OrderModel, OrderRefs, OrderInfo, OrderItem, DerivedData, OrderMeta,
)


def _make_model():
    return OrderModel(
        refs=OrderRefs(seller_id="acme", buyer_id="buyer_a", terms_id="default_usd"),
        order=OrderInfo(
            order_no="TEST01", format="standard", quote_no="QT-TEST01",
            pi_number="PI-TEST01", ci_number="CI-TEST01", date="19 May 2026",
            currency="USD", price_unit="USD/PC",
        ),
        items=[
            OrderItem(
                no=1, item_uuid="abc123def456", part_no=None, standard="DIN 933",
                description_raw="HEX BOLT M8x25", description="HEX HEAD BOLT DIN 933 M8x25 ZP",
                quantity=50000, unit="pcs", weight_kg=290.0, barcode="GF-001",
                unit_price=28.50,
            ),
            OrderItem(
                no=2, item_uuid="xyz789ghi012", part_no=None, standard="DIN 934",
                description_raw="HEX NUT M8", description="HEX NUT DIN 934 M8 ZP",
                quantity=100000, unit="pcs", weight_kg=280.0, barcode="GF-002",
                unit_price=12.00,
            ),
        ],
        derived=DerivedData(total_items=2, total_qty=150000, has_weight=True),
        meta=OrderMeta(source_files=["test.xlsx"], parser_model="rules"),
    )


def test_roundtrip_json():
    model = _make_model()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        model.to_json(path)
        loaded = OrderModel.from_json(path)

        assert loaded.refs.seller_id == "acme"
        assert loaded.refs.buyer_id == "buyer_a"
        assert loaded.order.order_no == "TEST01"
        assert loaded.order.currency == "USD"
        assert len(loaded.items) == 2
        assert loaded.items[0].item_uuid == "abc123def456"
        assert loaded.items[0].unit_price == 28.50
        assert loaded.items[1].description == "HEX NUT DIN 934 M8 ZP"
        assert loaded.derived.total_items == 2
        assert loaded.derived.total_qty == 150000
    finally:
        Path(path).unlink(missing_ok=True)


def test_item_uuid_generation():
    uuid1 = OrderItem.generate_uuid()
    uuid2 = OrderItem.generate_uuid()
    assert len(uuid1) == 12
    assert uuid1 != uuid2


def test_to_dict_excludes_resolved():
    model = _make_model()
    d = model.to_dict()
    assert "resolved" not in d
    assert d["refs"]["seller_id"] == "acme"
    assert len(d["items"]) == 2
