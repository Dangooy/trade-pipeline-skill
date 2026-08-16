"""
understanding/buyer_matcher.py — buyer 多级匹配器

匹配优先级：
  1. manifest/hints 显式指定的 buyer_id
  2. legal_names 精确匹配（规范化后）
  3. aliases 精确匹配（规范化后）
  4. 模糊匹配（剥离法律后缀后核心名相等；aliases 不参与，歧义即阻断）
  5. 全部未命中 → raise BuyerMatchError（硬阻断）

禁止：返回 None、静默跳过、继续流转到 Writer。
"""
import re

# 模糊匹配的核心名最短长度：剥离法律后缀后的核心名短于此值不参与模糊匹配。
MIN_FUZZY_LEN = 5

# 公司名中的法律形式后缀词（大小写无关，token 级剥离标点后比对）。
# 模糊匹配只比对剥离这些词之后的"核心名"。
LEGAL_SUFFIX_TOKENS = {
    # 英语系
    "llc", "ltd", "co", "corp", "inc", "limited", "liability", "company",
    "llp", "plc", "pte", "pty", "holdings",
    # 欧陆
    "gmbh", "bv", "nv", "srl", "sa", "sarl", "ag", "oy", "ab", "aps", "kft",
    # 俄语系（拉丁转写 + 西里尔）
    "ooo", "zao", "oao", "pao", "jsc", "pjsc", "cjsc",
    "ооо", "зао", "оао", "пао", "ао", "ип",
}


class BuyerMatchError(Exception):
    """buyer 匹配失败，必须进入 review。不允许被静默吞掉。"""

    def __init__(self, extracted_name: str, candidates: list[dict]):
        self.extracted_name = extracted_name
        self.candidates = candidates
        super().__init__(
            f"buyer 匹配失败: '{extracted_name}'\n"
            f"已知 buyers: {[c.get('id', c) for c in candidates]}"
        )


def normalize(name: str) -> str:
    """规范化：去引号/括号/空白/大小写，保留核心文字"""
    if not name:
        return ""
    name = name.strip()
    # 去除各种引号和括号
    name = re.sub(r'[«»"""\'\u201c\u201d\u2018\u2019`]', '', name)
    # 多空格合一
    name = re.sub(r'\s+', ' ', name)
    return name.lower().strip()


def _core_name(norm: str) -> str:
    """
    剥离法律形式词，得到公司"核心名"。只剥**开头连续段 + 结尾连续段**，
    不从名字中间剥。

    "global fasteners llc"         → "global fasteners"（英语后缀在结尾）
    "global fasteners llc."        → "global fasteners"（token 级剥标点）
    "ооо метиз трейдинг"           → "метиз трейдинг"（俄语法律形式是前缀）
    "global fasteners trading llc" → "global fasteners trading"（trading 是业务词，不剥）
    "global fasteners limited liability company" → "global fasteners"（结尾连续后缀链）

    中间不剥的原因（B1 修复）："Alpha Co Trading Ltd" 若把中间的 "co" 剥掉，
    核心名变成 "alpha trading"，与另一家 "Alpha Trading LLC" 的核心名相等，
    唯一命中即接受——A 客户的单据抬头会写上 B 客户。中间含法律词的名字
    （"Alpha Ltd Trading Co" → "alpha ltd trading"）宁可匹配不上进 review
    人工确认，也不冒错配风险。
    """
    tokens = [t.strip(".,;:&()[]-") for t in norm.split()]
    tokens = [t for t in tokens if t]
    i = 0
    while i < len(tokens) and tokens[i] in LEGAL_SUFFIX_TOKENS:
        i += 1
    j = len(tokens)
    while j > i and tokens[j - 1] in LEGAL_SUFFIX_TOKENS:
        j -= 1
    return " ".join(tokens[i:j])


def match_buyer(
    buyer_name_en: str | None,
    buyer_name_ru: str | None,
    buyer_name_cn: str | None,
    config: dict,
    hint_buyer_id: str | None = None,
) -> str:
    """
    多级 buyer 匹配，失败硬阻断。
    返回 buyer_id（config.yaml buyers 的 key）。

    参数:
        buyer_name_en/ru/cn: LLM 提取的买方名称（任一非空即可）
        config: 完整 config dict（含 buyers 段）
        hint_buyer_id: manifest/CLI 显式指定的 buyer_id

    返回:
        str — buyer_id

    抛出:
        BuyerMatchError — 全部未命中时硬阻断
    """
    buyers = config.get("buyers", {})

    # ── 优先级 0：_new 占位模式 ──
    if hint_buyer_id == "_new":
        placeholder_id = "_placeholder"
        if placeholder_id not in buyers:
            buyers[placeholder_id] = {
                "name_en": "TBD — To Be Confirmed",
                "name_ru": None,
                "legal_names": [],
                "aliases": [],
                "address": "",
                "address_lines": [],
                "contact": "",
                "email": "",
                "inn": "",
            }
        return placeholder_id

    if not buyers:
        raise BuyerMatchError("(config 中无 buyers)", [])

    # ── 优先级 1：显式指定 ──
    if hint_buyer_id:
        if hint_buyer_id in buyers:
            return hint_buyer_id
        raise BuyerMatchError(
            hint_buyer_id,
            _build_candidates(buyers),
        )

    # 提取名称（按优先级取第一个非空）
    extracted = ""
    for name in (buyer_name_en, buyer_name_ru, buyer_name_cn):
        if name and name.strip():
            extracted = name.strip()
            break

    if not extracted:
        raise BuyerMatchError("(空/未提取到 buyer 名称)", _build_candidates(buyers))

    norm_extracted = normalize(extracted)

    # ── 优先级 2：legal_names 精确匹配 ──
    for buyer_id, buyer in buyers.items():
        for legal in buyer.get("legal_names", []):
            if normalize(legal) == norm_extracted:
                return buyer_id

    # ── 优先级 3：aliases 规范化匹配 ──
    for buyer_id, buyer in buyers.items():
        for alias in buyer.get("aliases", []):
            if normalize(alias) == norm_extracted:
                return buyer_id

    # ── 优先级 4：模糊匹配（法律后缀剥离后核心名相等） ──
    # 修复（P0-1）：
    #   (1) aliases 不参与模糊匹配——短别名（如 "GF"、"Apex"）做子串匹配会把
    #       "GF Industrial Supply"、"Apexon" 等毫不相干的公司误匹配走。
    #       aliases 只允许精确匹配（已由优先级 3 覆盖）。
    #   (2) 只比对剥离法律后缀后的"核心名"是否相等：
    #       - 多出实词（Trading / International / & Nut）→ 核心名不等 → 拒绝
    #       - 仅法律后缀不同（Co / Corp / LLC / Ltd）→ 核心名相等 → 接受
    #       后者是显式设计决策：现实中仅后缀不同几乎总是同一家公司；
    #       若某客户确有 "X Co" 与 "X Corp" 两个不同法人，请把各自全名
    #       配进 legal_names 走精确匹配，并接受模糊层无法区分它们。
    extracted_core = _core_name(norm_extracted)
    fuzzy_matches = []
    if extracted_core and len(extracted_core) >= MIN_FUZZY_LEN:
        for buyer_id, buyer in buyers.items():
            candidate_names = (
                buyer.get("legal_names", [])
                + [buyer.get("name_en", ""), buyer.get("name_ru", "")]
            )
            for name in candidate_names:
                name_core = _core_name(normalize(name))
                if name_core and name_core == extracted_core:
                    fuzzy_matches.append(buyer_id)
                    break

    # 唯一命中才接受；多个不同 buyer 命中 → 有歧义，硬阻断交人工
    if len(set(fuzzy_matches)) == 1:
        return fuzzy_matches[0]

    # ── 优先级 5：全部未命中 / 歧义 → 硬阻断 ──
    raise BuyerMatchError(extracted, _build_candidates(buyers))


def _build_candidates(buyers: dict) -> list[dict]:
    """构造候选列表，供错误信息和 review.json 使用"""
    return [
        {
            "id": k,
            "name": v.get("name_en", ""),
            "aliases": v.get("aliases", []),
        }
        for k, v in buyers.items()
    ]
