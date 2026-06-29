"""Tests for field canonicalization: standard normalization, CN→EN translation."""
from trade_pipeline.understanding.canonicalizer import canonicalize


def test_standard_normalization():
    rfq = {"items": [{"description": "hex bolt din 933 m8x25", "standard": "din  933"}]}
    result = canonicalize(rfq)
    assert result["items"][0]["standard"] == "DIN 933"


def test_standard_extraction_from_description():
    rfq = {"items": [{"description": "HEX BOLT DIN 933 M8x25 ZP", "standard": None}]}
    result = canonicalize(rfq)
    assert result["items"][0]["standard"] == "DIN 933"


def test_cn_to_en_translation():
    rfq = {"items": [{"description": "平垫圈 DIN 125 M8", "standard": None}]}
    result = canonicalize(rfq)
    assert "FLAT WASHER" in result["items"][0]["description"]


def test_spring_washer_translation():
    rfq = {"items": [{"description": "弹簧垫圈 M10", "standard": None}]}
    result = canonicalize(rfq)
    assert "SPRING LOCK WASHER" in result["items"][0]["description"]


def test_hex_bolt_translation():
    rfq = {"items": [{"description": "六角螺栓 DIN 933 M12x40", "standard": None}]}
    result = canonicalize(rfq)
    assert "HEX HEAD BOLT" in result["items"][0]["description"]


def test_group_key_extraction():
    rfq = {"items": [
        {"description": "HEX HEAD BOLT DIN 933 M8x25 ZP", "standard": "DIN 933"},
    ]}
    result = canonicalize(rfq)
    gk = result["items"][0].get("group_key", "")
    assert "DIN 933" in gk
    assert "HEX HEAD BOLT" in gk


def test_unit_normalization():
    rfq = {"format": "standard", "items": [
        {"description": "BOLT", "standard": None, "unit": "шт"},
    ]}
    result = canonicalize(rfq)
    assert result["items"][0]["unit"] == "pcs"


def test_unit_tons_for_washers():
    rfq = {"format": "washers_mar", "items": [
        {"description": "WASHER", "standard": None, "unit": ""},
    ]}
    result = canonicalize(rfq)
    assert result["items"][0]["unit"] == "tons"
