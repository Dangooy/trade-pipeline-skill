"""Tests for multi-level buyer matching."""

import pytest

from trade_pipeline.understanding.buyer_matcher import match_buyer, BuyerMatchError


SAMPLE_CONFIG = {
    "buyers": {
        "global_fasteners": {
            "name_en": "Global Fasteners LLC",
            "name_ru": None,
            "legal_names": ["Global Fasteners LLC", "Global Fasteners Limited Liability Company"],
            "aliases": ["GF", "Global Fasteners"],
            "address": "Chicago, IL, USA",
        },
        "metiz_trading": {
            "name_en": 'OOO "Metiz Trading"',
            "name_ru": 'ООО "Метиз Трейдинг"',
            "legal_names": ['OOO "Metiz Trading"', 'ООО "Метиз Трейдинг"'],
            "aliases": ["Metiz Trading", "Метиз Трейдинг"],
            "address": "Moscow, Russia",
        },
    }
}


def test_exact_legal_name_match():
    result = match_buyer(
        buyer_name_en="Global Fasteners LLC",
        buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "global_fasteners"


def test_alias_match():
    result = match_buyer(
        buyer_name_en="GF",
        buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "global_fasteners"


def test_russian_legal_name():
    result = match_buyer(
        buyer_name_en=None,
        buyer_name_ru='ООО "Метиз Трейдинг"',
        buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "metiz_trading"


def test_fuzzy_substring_match():
    result = match_buyer(
        buyer_name_en="Metiz",
        buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "metiz_trading"


def test_hint_buyer_id_overrides():
    result = match_buyer(
        buyer_name_en="something random",
        buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
        hint_buyer_id="global_fasteners",
    )
    assert result == "global_fasteners"


def test_placeholder_new_buyer():
    result = match_buyer(
        buyer_name_en=None, buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
        hint_buyer_id="_new",
    )
    assert result == "_placeholder"


def test_no_match_raises_error():
    with pytest.raises(BuyerMatchError) as exc_info:
        match_buyer(
            buyer_name_en="Totally Unknown Company XYZ",
            buyer_name_ru=None, buyer_name_cn=None,
            config=SAMPLE_CONFIG,
        )
    assert "Totally Unknown Company XYZ" in str(exc_info.value)
    assert exc_info.value.candidates


def test_empty_name_raises_error():
    with pytest.raises(BuyerMatchError):
        match_buyer(
            buyer_name_en="", buyer_name_ru=None, buyer_name_cn=None,
            config=SAMPLE_CONFIG,
        )


def test_hint_nonexistent_raises_error():
    with pytest.raises(BuyerMatchError):
        match_buyer(
            buyer_name_en=None, buyer_name_ru=None, buyer_name_cn=None,
            config=SAMPLE_CONFIG,
            hint_buyer_id="does_not_exist",
        )


def test_quotes_normalized():
    """Russian quotes «» and "" should be normalized during matching."""
    result = match_buyer(
        buyer_name_en=None,
        buyer_name_ru='ООО «Метиз Трейдинг»',
        buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "metiz_trading"
