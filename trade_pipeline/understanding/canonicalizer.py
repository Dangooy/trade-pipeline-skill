"""
understanding/canonicalizer.py — RFQ Canonical 字段标准化

标准化处理：
  - quantity 单位统一（pcs / kgs / tons）
  - 标准号规范化（DIN 933 → DIN 933，去多余空格）
  - description 统一英文格式
  - group_key 提取（按 DIN/ISO 标准分组）
"""
import re

from .llm_parser import _extract_standard


def canonicalize(rfq: dict) -> dict:
    """
    标准化 RFQ canonical dict 中的字段。

    就地修改 items 列表中的每个 item。
    返回修改后的 rfq。
    """
    for item in rfq.get("items", []):
        _normalize_standard(item)
        _normalize_description(item)
        _normalize_unit(item, rfq.get("format", "standard"))
        _extract_group_key(item)

    return rfq


def _normalize_standard(item: dict) -> None:
    """标准号规范化"""
    std = item.get("standard")
    if not std:
        extracted = _extract_standard(item.get("description", ""))
        if extracted:
            item["standard"] = extracted
        return

    # 规范化：去多余空格，大写
    std = re.sub(r"\s+", " ", std.strip()).upper()
    item["standard"] = std


def _normalize_description(item: dict) -> None:
    """描述规范化：去多余空格，中文产品名翻译为英文"""
    desc = item.get("description", "")
    if not desc:
        desc = item.get("description_raw", "")

    # 去多余空格
    desc = re.sub(r"\s+", " ", desc.strip())

    # 中文产品名 → 英文
    cn_en = [
        ("平垫圈", "FLAT WASHER"),
        ("弹簧垫圈", "SPRING LOCK WASHER"),
        ("弹垫", "SPRING LOCK WASHER"),
        ("六角螺栓", "HEX HEAD BOLT"),
        ("六角螺母", "HEX NUT"),
        ("内六角螺钉", "HEX SOCKET HEAD CAP SCREW"),
        ("自攻螺钉", "TAPPING SCREW"),
        ("盖形螺母", "CAP NUT"),
        ("法兰螺母", "FLANGE HEX NUT"),
        ("尼龙锁紧螺母", "NYLON INSERT HEX NUT"),
    ]
    for cn, en in cn_en:
        if cn in desc:
            desc = desc.replace(cn, en)
            break

    item["description"] = desc


def _normalize_unit(item: dict, fmt: str) -> None:
    """单位规范化"""
    unit = item.get("unit", "")
    if not unit:
        item["unit"] = "tons" if fmt == "washers_mar" else "pcs"
        return

    unit_lower = unit.lower().strip()
    unit_map = {
        "pcs": "pcs",
        "шт": "pcs",
        "pc": "pcs",
        "pieces": "pcs",
        "kg": "kgs",
        "kgs": "kgs",
        "ton": "tons",
        "tons": "tons",
        "t": "tons",
    }
    item["unit"] = unit_map.get(unit_lower, unit_lower)


def _extract_group_key(item: dict) -> None:
    """提取分组键（用于报价单分组标题行）"""
    desc = item.get("description", "")
    std = item.get("standard", "")

    if not std:
        item["group_key"] = "__OTHER__"
        return

    # 提取产品类型
    desc_upper = desc.upper()
    if "HEX HEAD BOLT" in desc_upper:
        ptype = "HEX HEAD BOLT"
    elif "HEX SOCKET HEAD CAP" in desc_upper:
        ptype = "HEX SOCKET HEAD CAP SCREW"
    elif "BUTTON HEAD" in desc_upper:
        ptype = "SOCKET BUTTON HEAD SCREW"
    elif "SET SCREW" in desc_upper:
        ptype = "HEX SOCKET SET SCREW"
    elif "FLANGE HEX NUT" in desc_upper:
        ptype = "FLANGE HEX NUT"
    elif "NYLON INSERT" in desc_upper:
        ptype = "NYLON INSERT HEX NUT"
    elif "HEX NUT" in desc_upper:
        ptype = "HEX NUT"
    elif "THIN NUT" in desc_upper or "DIN439" in desc_upper.replace(" ", ""):
        ptype = "CHAMFERED HEXAGON THIN NUT"
    elif "CAP NUT" in desc_upper:
        ptype = "CAP NUT"
    elif "WASHER" in desc_upper or "垫圈" in desc_upper:
        ptype = "FLAT WASHER"
    elif "SPRING LOCK WASHER" in desc_upper or "DIN7980" in desc_upper.replace(" ", ""):
        ptype = "SPRING LOCK WASHER"
    elif "TAPPING" in desc_upper:
        ptype = "TAPPING SCREW"
    else:
        ptype = ""

    # 提取材质
    mat_m = re.search(r"(A2-70|A4-80|A2|A4|ZP)", desc, re.IGNORECASE)
    mat = mat_m.group(1).upper() if mat_m else ""

    parts = [std]
    if ptype:
        parts.append(ptype)
    if mat:
        parts.append(mat)
    item["group_key"] = " — ".join(parts)
