"""
understanding/buyer_matcher.py — buyer 多级匹配器

匹配优先级：
  1. manifest/hints 显式指定的 buyer_id
  2. legal_names 精确匹配（规范化后）
  3. aliases 精确匹配（规范化后）
  4. 模糊匹配（子串包含）
  5. 全部未命中 → raise BuyerMatchError（硬阻断）

禁止：返回 None、静默跳过、继续流转到 Writer。
"""
import re


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

    # ── 优先级 4：模糊匹配（子串包含，双向） ──
    for buyer_id, buyer in buyers.items():
        all_names = (
            buyer.get("legal_names", [])
            + buyer.get("aliases", [])
            + [buyer.get("name_en", ""), buyer.get("name_ru", "")]
        )
        for name in all_names:
            norm_name = normalize(name)
            if not norm_name:
                continue
            if norm_name in norm_extracted or norm_extracted in norm_name:
                return buyer_id

    # ── 优先级 5：全部未命中 → 硬阻断 ──
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
