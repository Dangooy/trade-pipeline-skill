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


def test_short_fragment_no_longer_fuzzy_matches():
    """P0-1 修复：短片段 'Metiz'（5 字符，占 'metiz trading' 长度 <60%）
    不再模糊匹配——短词模糊匹配是跨公司误匹配的根源，'宁愧勿纵'策略下应硬阻断。
    真要匹配 'Metiz' 请把它加进 aliases 走精确匹配。"""
    with pytest.raises(BuyerMatchError):
        match_buyer(
            buyer_name_en="Metiz",
            buyer_name_ru=None, buyer_name_cn=None,
            config=SAMPLE_CONFIG,
        )


def test_full_legal_name_with_trailing_punctuation_still_fuzzy_matches():
    """长度高度重合的名称（仅尾部标点/后缀差异）仍应模糊命中。"""
    result = match_buyer(
        buyer_name_en="Global Fasteners LLC.",  # 仅多一个句点
        buyer_name_ru=None, buyer_name_cn=None,
        config=SAMPLE_CONFIG,
    )
    assert result == "global_fasteners"


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


# ── 负样本：相似但不同的公司必须被拒绝匹配（P0-1 回归防线） ──────────────
#
# 审查指出原实现无任何负样本测试。以下用例都是"看起来相关、实则可能是
# 另一家公司"的输入，必须硬阻断进 review，绝不能静默匹配到错误 buyer——
# 匹配错 = PI/CI 抬头/地址写错 = 真实货款损失。

NEG_CONFIG = {
    "buyers": {
        "global_fasteners": {
            "name_en": "Global Fasteners LLC",
            "name_ru": None,
            "legal_names": ["Global Fasteners LLC"],
            "aliases": ["GF", "Global Fasteners"],
            "address": "Chicago, IL, USA",
        },
        "apex_bolt": {
            "name_en": "Apex Bolt Co",
            "name_ru": None,
            "legal_names": ["Apex Bolt Co"],
            "aliases": ["Apex"],
            "address": "Ohio, USA",
        },
    }
}


@pytest.mark.parametrize("extracted", [
    "Global Fasteners Trading LLC",   # 可能是另一家公司，仅共享前缀
    "Global Fasteners International",  # 同上
    "GF Industrial Supply",           # 短别名 'GF' 恰是其子串——最阴险的误匹配
    "Apexon Software Ltd",            # 'Apex' 是 'Apexon' 的子串，跨行业
    "Apex Logistics Group",           # 'Apex' 撞名，实为物流公司
])
def test_similar_but_different_company_is_rejected(extracted):
    """相似但不同的公司名必须硬阻断，不得误匹配到已知 buyer。"""
    with pytest.raises(BuyerMatchError):
        match_buyer(
            buyer_name_en=extracted,
            buyer_name_ru=None, buyer_name_cn=None,
            config=NEG_CONFIG,
        )


def test_suffix_variant_treated_as_same_company():
    """设计决策（显式记录）：仅法律后缀不同的名称视为同一公司。
    'Apex Bolt Corp' 与配置中的 'Apex Bolt Co' 核心名相同（apex bolt），
    模糊匹配接受。若现实中确有 'X Co' 与 'X Corp' 两个不同法人，
    须把各自全名配进 legal_names 精确匹配，模糊层不区分它们。"""
    assert match_buyer("Apex Bolt Corp", None, None, config=NEG_CONFIG) == "apex_bolt"
    assert match_buyer("Global Fasteners Ltd", None, None, config=NEG_CONFIG) == "global_fasteners"


def test_extra_real_word_is_rejected_even_with_same_suffix():
    """与后缀变体相对照：多出实词（非法律后缀）必须拒绝。"""
    with pytest.raises(BuyerMatchError):
        match_buyer("Apex Bolt Trading Co", None, None, config=NEG_CONFIG)


def test_alias_only_matches_exactly_not_as_substring():
    """短别名（GF/Apex）只能精确匹配，不能作为子串把无关公司拽进来。"""
    # 精确等于别名 → 命中（优先级 3）
    assert match_buyer("GF", None, None, config=NEG_CONFIG) == "global_fasteners"
    assert match_buyer("Apex", None, None, config=NEG_CONFIG) == "apex_bolt"
    # 别名作为子串出现在更长的无关名称里 → 不得命中
    with pytest.raises(BuyerMatchError):
        match_buyer("GF Global Supplies Inc", None, None, config=NEG_CONFIG)


# ── B1 回归防线：法律词出现在名字**中间**时不得被剥除 ──────────────────
#
# 修复前 _core_name 从任意位置剥后缀 token："Alpha Co Trading Ltd" 的中间
# "co" 被剥掉 → 核心名 "alpha trading"，与另一家 "Alpha Trading LLC" 的
# 核心名相等 → 唯一命中即接受 → A 客户的单据抬头写上 B 客户。
# 修复后只剥开头连续段（俄语前缀）+ 结尾连续段（英语后缀链），中间保留。

ALPHA_CONFIG = {
    "buyers": {
        "alpha_trading": {
            "name_en": "Alpha Trading LLC",
            "name_ru": None,
            "legal_names": ["Alpha Trading LLC"],
            "aliases": [],
            "address": "Berlin, DE",
        }
    }
}


@pytest.mark.parametrize("extracted", [
    "Alpha Co Trading Ltd",        # 中间 "co"：修复前剥掉后撞 alpha trading
    "Alpha Holdings Trading Ltd",  # 中间 "holdings"：同型碰撞
    "Alpha Limited Trading Co",    # 中间 "limited"
])
def test_mid_position_legal_word_is_kept_and_rejected(extracted):
    """名字中间的法律词不得剥除——剥除会造成跨公司核心名碰撞，必须硬阻断。"""
    with pytest.raises(BuyerMatchError):
        match_buyer(extracted, None, None, config=ALPHA_CONFIG)


def test_core_name_strips_leading_and_trailing_runs_only():
    """新语义直接固化：只剥首段+尾段的后缀 run，中间保留。"""
    from trade_pipeline.understanding.buyer_matcher import _core_name
    assert _core_name("alpha co trading ltd") == "alpha co trading"
    assert _core_name("alpha ltd trading co") == "alpha ltd trading"
    assert _core_name("ооо метиз трейдинг") == "метиз трейдинг"
    assert _core_name("global fasteners limited liability company") == "global fasteners"
    assert _core_name("global fasteners llc.") == "global fasteners"


def test_russian_prefix_fuzzy_still_matches():
    """俄语法律形式是前缀：剥前缀后的核心名模糊匹配必须继续工作。"""
    assert match_buyer(
        'ООО «Метиз Трейдинг»'.lower(), None, None, config=SAMPLE_CONFIG
    ) == "metiz_trading"
    # 提取名无前缀 vs 配置带前缀 → 核心名仍相等（前缀只在首段剥）
    assert match_buyer("Metiz Trading", None, None, config=SAMPLE_CONFIG) == "metiz_trading"


def test_all_suffix_name_yields_empty_core_and_no_match():
    """名字全是法律词时核心名为空,不得参与模糊匹配(空串守卫)。"""
    with pytest.raises(BuyerMatchError):
        match_buyer("Ltd Co LLC", None, None, config=ALPHA_CONFIG)
