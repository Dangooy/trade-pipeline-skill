"""Verify actual invoice, shipment and packing fields against their source cells."""
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string
from openpyxl.utils.exceptions import InvalidFileException

HEADER_LIMIT = 80
ROW_LIMIT = 5000
ITEM_FIELDS = {
    "shipped_quantity": ("shipped quantity", "actual shipped qty", "实发数量", "实际出货数量"),
    "invoice_unit_price": ("invoice unit price", "actual invoice price", "开票单价", "实际开票单价"),
    "net_kg": ("net kg", "net weight kg", "actual net weight kg", "实际净重 kg", "净重 kg"),
    "cartons": ("cartons", "actual cartons", "carton count", "箱数", "实际箱数"),
}
DETAIL_FIELDS = {
    "ci_number": ("ci number", "commercial invoice no", "invoice number", "商业发票号", "开票编号"),
    "gross_kg": ("gross kg", "total gross weight kg", "actual gross kg", "实际总毛重 kg", "总毛重 kg"),
    "packing": ("packing", "packing description", "实际包装", "包装说明"),
    "pallets": ("pallets", "pallet count", "actual pallets", "托盘数", "实际托盘数"),
    "measurement_m3": ("measurement m3", "total measurement m3", "实际总体积 m3", "总体积 m3"),
}
PRODUCT_FIELDS = ("description", "spec", "material", "finish", "unit")
DESCRIPTION_HEADERS = ("description", "product", "item description", "品名", "商品名称")
SPEC_HEADERS = ("spec", "specification", "规格", "型号")
UNIT_HEADERS = ("unit", "qty unit", "quantity unit", "计量单位", "数量单位", "单位")
CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,4})", re.I)
QUOTE = re.compile(r"quot(?:e|ation)|proforma|询价|报价|形式发票")
ACTUAL = re.compile(
    r"shipment|dispatch|packing list|commercial invoice|actual packing|actuals|"
    r"出货|实发|发运|装箱|商业发票|实际开票|出库"
)


def norm(value):
    return " ".join(re.sub(r"[^\w]|_", " ", str(value or "").casefold()).split())


def normalize_unit(unit):
    return {
        "pc": "pcs", "pcs": "pcs", "件": "pcs",
        "kg": "kgs", "kgs": "kgs", "千克": "kgs",
        "ton": "tons", "tons": "tons", "吨": "tons",
    }.get(norm(unit))


def actual_entries(data):
    for key in DETAIL_FIELDS:
        if key in data["details"]:
            yield f"details.{key}", data["details"][key]
    for number, row in enumerate(data["items"], 1):
        for key in ITEM_FIELDS:
            if key in row:
                yield f"items.{number}.{key}", row[key]


def manual_facts(data):
    """Manual candidates require their own, explicit desktop confirmation."""
    entries = {
        address: value for address, value in actual_entries(data)
        if data["evidence"][address][0] == "confirmed"
    }
    if not entries:
        return {}
    return {
        "fields": entries,
        "parties": {key: data["details"].get(key) for key in ("seller", "buyer")},
        "products": [{key: row.get(key) for key in PRODUCT_FIELDS} for row in data["items"]],
    }


def same_value(expected, actual):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return Decimal(str(expected)) == Decimal(str(actual).strip())
        except InvalidOperation:
            return False
    return isinstance(actual, str) and " ".join(expected.split()) == " ".join(actual.split())


def eligible_sheets(path):
    if path.suffix.lower() != ".xlsx" or path.stat().st_size > 20 * 1024 * 1024:
        return {}
    try:
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except (InvalidFileException, BadZipFile, ValueError, OSError):
        return {}
    try:
        return {
            sheet.title.casefold(): list(sheet.iter_rows(
                min_row=1, max_row=sheet.max_row, max_col=sheet.max_column, values_only=True,
            ))
            for sheet in workbook.worksheets
            if (ACTUAL.search(norm(sheet.title)) and not QUOTE.search(norm(sheet.title))
                and sheet.max_row and sheet.max_column
                and sheet.max_row <= ROW_LIMIT and sheet.max_column <= HEADER_LIMIT)
        }
    finally:
        workbook.close()


def locate(reference, sources):
    file_hint, delimiter, locator = reference.rpartition("#")
    if not delimiter:
        locator = reference
    sheet, sep, coordinate = locator.rpartition("!")
    address = CELL.fullmatch(coordinate.strip())
    if not sep or not address:
        return None
    sheet = sheet.strip()
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    row = int(address[2]) - 1
    col = column_index_from_string(address[1].upper()) - 1
    matches = [
        (path, sheets[sheet.casefold()]) for path, sheets in sources.items()
        if sheet.casefold() in sheets
        and (not file_hint or file_hint in (path.name, str(path)))
    ]
    if len(matches) != 1:
        return None
    path, rows = matches[0]
    if row >= len(rows) or col >= len(rows[row]):
        return None
    return path, rows, row, col


def line_address_matches(data, order_row, field, rows, row, col):
    product = data["items"][order_row]
    for possible_header in reversed(rows[:row]):
        labels = [norm(cell) for cell in possible_header]
        if not (set(labels) & set(DESCRIPTION_HEADERS)):
            continue
        if labels[col] not in ITEM_FIELDS[field]:
            return False
        product_col = next(index for index, name in enumerate(labels) if name in DESCRIPTION_HEADERS)
        description = norm(product.get("description"))
        if not description or description != norm(rows[row][product_col]):
            return False
        for index, name in enumerate(labels):
            if name in UNIT_HEADERS and (
                not normalize_unit(product.get("unit"))
                or normalize_unit(rows[row][index]) != normalize_unit(product["unit"])
            ):
                return False
        if any(name in SPEC_HEADERS for name in labels):
            spec_col = next(index for index, name in enumerate(labels) if name in SPEC_HEADERS)
            if not norm(product.get("spec")) or norm(product["spec"]) != norm(rows[row][spec_col]):
                return False
            keys = ("description", "spec")
            repeated = [r for r in rows if norm(r[product_col]) == description
                        and norm(r[spec_col]) == norm(product["spec"])]
        else:
            keys = ("description",)
            repeated = [r for r in rows if norm(r[product_col]) == description]
        identity = tuple(norm(product.get(key)) for key in keys)
        return len(repeated) == 1 and sum(
            tuple(norm(item.get(key)) for key in keys) == identity for item in data["items"]
        ) == 1
    return False


def verified_data(data, source_paths, manual_attested=False):
    """Return the data safe to pass to writers, and names of rejected proposed facts."""
    accepted = deepcopy(data)
    sources = None  # Documents without actual fields do not parse attachments again.
    rejected = []
    used_cells = set()
    for address, expected in actual_entries(data):
        origin, reference = data["evidence"][address]
        section, _, field = address.rpartition(".")
        valid = origin == "confirmed" and manual_attested
        if origin == "source":
            if sources is None:
                sources = {Path(path): eligible_sheets(Path(path)) for path in source_paths}
            match = locate(reference, sources)
            if match:
                file, rows, row, col = match
                key = (file, id(rows), row, col)
                if key not in used_cells and same_value(expected, rows[row][col]):
                    if section == "details":
                        valid = col > 0 and norm(rows[row][col - 1]) in DETAIL_FIELDS[field]
                    else:
                        index = int(section.split(".")[1]) - 1
                        valid = line_address_matches(data, index, field, rows, row, col)
                    if valid:
                        used_cells.add(key)
        if not valid:
            values = (accepted["details"] if section == "details"
                      else accepted["items"][int(section.split(".")[1]) - 1])
            del values[field]
            del accepted["evidence"][address]
            rejected.append(address)
    return accepted, rejected
