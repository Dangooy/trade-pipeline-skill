"""
understanding/llm_parser.py — 询价单解析器（规则 + Claude API）

两种模式：
  1. 规则模式（默认）：从 ExtractedDocument 的结构化表格行直接提取
  2. LLM 模式：调用 Claude API 解析，接入 L2 缓存

输出 RFQ Canonical dict。
"""
import json
import os
import re

from ..extractors.base import ExtractedDocument
from .cache import UnderstandingCache

# RFQ Canonical 版本号，变更时 L2 缓存自动失效
PROMPT_VERSION = "v1.0"
SCHEMA_VERSION = "v1.0"
MODEL_NAME = "claude-sonnet-4-20250514"


def parse(
    doc: ExtractedDocument,
    use_llm: bool = False,
    cache_dir: str | None = None,
) -> dict:
    """
    解析 ExtractedDocument 为 RFQ Canonical dict。

    参数:
        doc: ExtractedDocument 实例
        use_llm: 是否使用 Claude API（默认 False，用规则）
        cache_dir: L2 缓存目录

    返回:
        RFQ Canonical dict
    """
    if use_llm:
        return _parse_with_llm(doc, cache_dir)
    return _parse_with_rules(doc)


# ── 规则模式 ────────────────────────────────────────────────────────────

def _parse_with_rules(doc: ExtractedDocument) -> dict:
    """规则模式：从结构化表格行直接提取 RFQ canonical。"""
    fmt = doc.meta.get("format", "standard")
    rows = doc.blocks[0].rows if doc.blocks else []

    if fmt == "washers_mar":
        return _parse_washers_rules(rows, doc)
    return _parse_standard_rules(rows, doc)


def _find_header_row(rows: list[list[str]]) -> int:
    """动态查找表头行（扫描前 10 行，找到含最多已知列名的行）"""
    known = {
        "序号", "产品编码", "产品描述", "数量", "计量单位", "表面处理", "总重量",
        "规格", "报价", "单价", "barcode", "commodity description", "pcs",
        "total quantity", "kg/mpcs", "quantity in box", "uom",
    }
    best_row, best_score = 0, 0
    for i, row in enumerate(rows[:10]):
        score = 0
        for cell in row:
            cell_lower = cell.strip().lower().replace("\n", "")
            for kw in known:
                if kw in cell_lower:
                    score += 1
                    break
        if score > best_score:
            best_score = score
            best_row = i
    return best_row


def _map_header(header: str) -> str | None:
    """将中英文列头映射为标准 key"""
    h = header.strip().replace("\n", " ").lower()
    mapping = [
        (["序号", "no.", "no", "item"], "no"),
        (["产品编码", "barcode", "part code", "code"], "barcode"),
        (["产品描述", "commodity description", "description", "品名"], "description"),
        (["规格"], "spec"),
        (["数量", "total quantity", "qty"], "quantity"),
        (["计量单位", "uom", "pcs", "unit"], "uom"),
        (["表面处理", "surface", "finish"], "finish"),
        (["总重量", "weight", "net weight"], "weight_kg"),
        (["kg/mpcs", "千件重"], "kg_mpcs"),
        (["quantity in box", "每箱数量", "箱入数"], "qty_box"),
        (["报价", "单价", "unit price", "price"], "price"),
    ]
    for keywords, key in mapping:
        for kw in keywords:
            if kw in h:
                return key
    return None


def _is_data_row(row: list[str], no_idx: int | None) -> bool:
    """判断是否为有效数据行（排除合计/备注/空行）"""
    text = " ".join(row).strip()
    if not text:
        return False
    skip_prefixes = ["合计", "总计", "合 计", "备注", "注：", "注:", "【",
                     "FOB", "fob", "尺寸依据", "材质", "镀锌", "根据图纸",
                     "汇率", "包装", "说明"]
    first = row[0].strip() if row else ""
    for prefix in skip_prefixes:
        if first.startswith(prefix):
            return False
    # 如果有序号列，检查序号是否为数字
    if no_idx is not None and no_idx < len(row):
        try:
            int(float(row[no_idx].strip()))
            return True
        except (ValueError, TypeError):
            return False
    return True


def _detect_currency_from_headers(headers: list[str]) -> tuple[str, str]:
    """从列头中检测货币和价格单位"""
    text = " ".join(headers).upper()
    has_weight_col = "总重量" in text or "WEIGHT" in text or "KGS" in text
    if "USD" in text:
        if "TON" in text:
            return "USD", "USD/TON"
        # 有总重量列 → 按吨计价
        if has_weight_col:
            return "USD", "USD/TON"
        return "USD", "USD/PC"
    if "CNY" in text or "RMB" in text or "人民币" in text:
        if "MPCS" in text or "千件" in text:
            return "CNY", "CNY/MPCS"
        return "CNY", "CNY/PC"
    return "CNY", "CNY/MPCS"


def _extract_buyer_from_rows(rows: list[list[str]], header_idx: int) -> str | None:
    """从表头之前的行中提取客户名称"""
    for row in rows[:header_idx]:
        text = " ".join(row).strip()
        m = re.search(r'客户[:：]\s*(\S+)', text)
        if m:
            return m.group(1)
        m = re.search(r'(?:buyer|customer)[:：]\s*(\S+)', text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _parse_standard_rules(rows: list[list[str]], doc: ExtractedDocument) -> dict:
    """standard 格式规则解析（支持中英文列头、动态表头行检测）"""
    if not rows:
        return _empty_rfq(doc, "standard")

    # 动态查找表头行
    header_idx = _find_header_row(rows)
    headers = rows[header_idx]

    # 构建列头映射 key -> col_index
    col_map: dict[str, int] = {}
    for i, h in enumerate(headers):
        key = _map_header(h)
        if key and key not in col_map:
            col_map[key] = i

    # 从列头检测货币
    currency, price_unit = _detect_currency_from_headers(headers)

    # 提取客户名
    buyer_name = _extract_buyer_from_rows(rows, header_idx)

    # 列索引
    no_idx = col_map.get("no")
    desc_idx = col_map.get("description", 0)
    barcode_idx = col_map.get("barcode")
    spec_idx = col_map.get("spec")
    qty_idx = col_map.get("quantity", 4)
    uom_idx = col_map.get("uom")
    weight_idx = col_map.get("weight_kg")
    kg_idx = col_map.get("kg_mpcs")
    qbox_idx = col_map.get("qty_box")
    finish_idx = col_map.get("finish")
    price_idx = col_map.get("price")

    # 从 meta 获取跨 Sheet 补充价格
    supp_prices = doc.meta.get("supplementary_prices", {})

    has_weight = weight_idx is not None or kg_idx is not None

    items = []
    for row in rows[header_idx + 1:]:
        if not _is_data_row(row, no_idx):
            continue

        desc = row[desc_idx].strip() if desc_idx < len(row) else ""
        if not desc:
            continue

        # 组合规格到描述
        spec = row[spec_idx].strip() if spec_idx is not None and spec_idx < len(row) else ""
        if spec and spec not in desc:
            desc = f"{desc} {spec}"

        barcode = row[barcode_idx].strip() if barcode_idx is not None and barcode_idx < len(row) else ""
        uom_raw = row[uom_idx].strip().lower() if uom_idx is not None and uom_idx < len(row) else "pcs"
        unit = "pcs" if uom_raw in ("pc", "pcs", "件", "只", "个") else uom_raw
        qty = _to_float(row[qty_idx]) if qty_idx < len(row) else 0
        weight = _to_float(row[weight_idx]) if weight_idx is not None and weight_idx < len(row) else None
        kg = _to_float(row[kg_idx]) if kg_idx is not None and kg_idx < len(row) else None
        qty_box = _to_int(row[qbox_idx]) if qbox_idx is not None and qbox_idx < len(row) else None
        finish = row[finish_idx].strip() if finish_idx is not None and finish_idx < len(row) else None

        standard = _extract_standard(desc)

        # 读取价格：优先主 Sheet 价格列，其次跨 Sheet 补充价格
        price = None
        if price_idx is not None and price_idx < len(row):
            p = _to_float(row[price_idx])
            if p > 0:
                price = p
        if price is None and barcode and barcode in supp_prices:
            price = supp_prices[barcode]

        item = {
            "description_raw": row[desc_idx].strip() if desc_idx < len(row) else "",
            "description": desc,
            "standard": standard,
            "part_no": None,
            "barcode": barcode,
            "quantity": qty,
            "unit": unit,
            "kg_mpcs": kg,
            "qty_box": qty_box,
            "unit_price": price,
        }
        if weight:
            item["weight_kg"] = weight
        if finish:
            item["finish"] = finish

        items.append(item)

    return {
        "buyer_name_en": buyer_name,
        "buyer_name_ru": None,
        "buyer_name_cn": None,
        "format": "standard",
        "currency": currency,
        "price_unit": price_unit,
        "has_weight": has_weight,
        "source_file": doc.source_path,
        "items": items,
    }


def _parse_washers_rules(rows: list[list[str]], doc: ExtractedDocument) -> dict:
    """washers_mar 格式规则解析"""
    items = []
    current_din = ""

    for row in rows[2:]:  # skip header rows (row 1: title, row 2: column headers)
        size = row[0].strip() if row else ""
        qty_str = row[3].strip() if len(row) > 3 else ""

        if not size:
            continue

        qty_tons = _to_float(qty_str)

        # DIN 标准标题行
        if re.match(r"DIN\w*", size, re.IGNORECASE) and not qty_tons:
            current_din = size
            continue

        # 数据行
        if re.match(r"M\d+", size) and qty_tons:
            if "125" in current_din.upper():
                desc = f"FLAT WASHER, DIN 125-1A, {size} ZP"
                standard = "DIN 125"
            elif "9021" in current_din.upper():
                desc = f"FLAT WASHER, DIN 9021, {size} ZP"
                standard = "DIN 9021"
            elif "127" in current_din.upper():
                desc = f"SPRING LOCK WASHER, DIN 127, {size} ZP"
                standard = "DIN 127"
            else:
                din_num = re.sub(r"[A-Za-z\s]", "", current_din.split()[0]) if current_din else ""
                desc = f"FLAT WASHER, DIN {din_num}, {size} ZP"
                standard = f"DIN {din_num}"

            items.append({
                "description_raw": f"{size} — {current_din}",
                "description": desc,
                "standard": standard,
                "part_no": None,
                "barcode": None,
                "quantity": qty_tons,
                "unit": "tons",
                "kg_mpcs": None,
                "qty_box": None,
                "din_group": current_din,
                "size": size,
            })

    return {
        "buyer_name_en": None,
        "buyer_name_ru": None,
        "buyer_name_cn": None,
        "format": "washers_mar",
        "currency": "USD",
        "price_unit": "USD/TON",
        "has_weight": False,
        "source_file": doc.source_path,
        "items": items,
    }


# ── LLM 模式 ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert trade document parser. Extract structured data from inquiry/RFQ documents.

Output JSON with this schema:
{
  "buyer_name_en": "string or null",
  "buyer_name_ru": "string or null",
  "format": "standard" or "washers_mar",
  "currency": "CNY" or "USD",
  "items": [
    {
      "description_raw": "original text",
      "description": "cleaned description",
      "standard": "DIN/ISO number or null",
      "barcode": "string or null",
      "quantity": number,
      "unit": "pcs" or "tons",
      "kg_mpcs": number or null,
      "qty_box": number or null
    }
  ]
}

Parse the following inquiry document and return ONLY valid JSON."""


def _parse_with_llm(doc: ExtractedDocument, cache_dir: str | None = None) -> dict:
    """LLM 模式：调用 Claude API，接入 L2 缓存。"""
    # L2 缓存检查
    cache = None
    if cache_dir:
        cache = UnderstandingCache(
            cache_dir, PROMPT_VERSION, SCHEMA_VERSION
        )
        cached = cache.get(doc.content_hash, MODEL_NAME)
        if cached:
            return cached

    # 调用 Claude API
    try:
        import anthropic
    except ImportError:
        print("WARNING: anthropic 包未安装，回退到规则模式")
        return _parse_with_rules(doc)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY 未设置，回退到规则模式")
        return _parse_with_rules(doc)

    try:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = anthropic.Anthropic(**client_kwargs)

        # 截取前 4000 字符（避免 token 过多）
        content = doc.content_text[:4000]

        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )

        result_text = response.content[0].text.strip()
        # 提取 JSON（可能被 markdown 包裹）
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        rfq = json.loads(result_text)

        # 补充必要字段
        rfq.setdefault("source_file", doc.source_path)
        rfq.setdefault("has_weight", False)
        rfq.setdefault("price_unit", "CNY/MPCS")

        # L2 缓存写入
        if cache:
            cache.put(doc.content_hash, MODEL_NAME, rfq)

        return rfq

    except Exception as e:
        print(f"WARNING: Claude API 调用失败 ({e})，回退到规则模式")
        return _parse_with_rules(doc)


# ── 辅助函数 ───────────────────────────────────────────────────────────

def _extract_standard(desc: str) -> str | None:
    """从描述中提取 DIN/ISO/ASTM/GB 标准号"""
    m = re.search(
        r"(DIN\s*\d+[-\dA-Za-z]*|ISO\s*\d+[-\dA-Za-z]*|ASTM\s+[A-Z][-\dA-Za-z]*|GB/?T?\s*\d+[-.\dA-Za-z]*)",
        desc, re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", m.group(1).upper()) if m else None


def _to_float(s: str) -> float:
    """安全转 float"""
    if not s or s.strip() == "" or s.strip().lower() == "none":
        return 0.0
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _to_int(s: str) -> int | None:
    """安全转 int"""
    if not s or s.strip() == "" or s.strip().lower() == "none":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _empty_rfq(doc: ExtractedDocument, fmt: str) -> dict:
    return {
        "buyer_name_en": None,
        "buyer_name_ru": None,
        "buyer_name_cn": None,
        "format": fmt,
        "currency": "CNY",
        "price_unit": "CNY/MPCS",
        "has_weight": False,
        "source_file": doc.source_path,
        "items": [],
    }
