"""Local workbook inspection and an internal quotation draft for WorkBuddy."""
import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

if __package__:
    from .workbook_output import save_workbook
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from workbook_output import save_workbook

DRAFT_COLUMNS = (
    ("description", "品名"), ("spec", "规格"), ("material", "材质"),
    ("finish", "表面处理"), ("quantity", "数量"), ("unit", "数量单位"),
    ("unit_price", "单价"), ("price_unit", "计价单位"), ("source", "来源（工作表 / 行）"),
)
DRAFT_FIELDS = (
    ("buyer", "买家"), ("seller", "卖家"), ("currency", "币种"),
    ("payment", "付款条件"), ("delivery", "贸易条款 / 地点"), ("lead_time", "交期"),
)
MAX_ROWS = 5000
MAX_COLUMNS = 80


class IntakeError(Exception):
    pass


def inspect_workbook(path, output):
    """Keep the original cell positions and flag formulas without cached values."""
    if path.stat().st_size > 20 * 1024 * 1024:
        raise IntakeError("表格超过 20 MB，请拆分后再试。")
    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        sheets = {}
        for sheet in workbook.worksheets:
            if sheet.max_row and sheet.max_row > MAX_ROWS:
                raise IntakeError(f"工作表 {sheet.title} 超过 5000 行，请拆分后再试。")
            if sheet.max_column and sheet.max_column > MAX_COLUMNS:
                raise IntakeError(f"工作表 {sheet.title} 超过 80 列，请精简后再试。")
            rows = {}
            for number, row in enumerate(sheet.values, 1):
                if number > MAX_ROWS or len(row) > MAX_COLUMNS:
                    raise IntakeError(f"工作表 {sheet.title} 超过读取范围，请拆分后再试。")
                cells = {get_column_letter(i): x for i, x in enumerate(row, 1) if x is not None}
                if cells:
                    rows[number] = cells
            sheets[sheet.title] = rows
    finally:
        workbook.close()

    formulas = load_workbook(path, read_only=True, keep_links=False)
    try:
        for sheet in formulas.worksheets:
            for row in sheet.iter_rows(min_row=1, min_col=1):
                for cell in row:
                    if cell.data_type == "f":
                        cells = sheets[sheet.title].setdefault(cell.row, {})
                        cells.setdefault(cell.column_letter, "待确认（原公式无缓存结果）")
    finally:
        formulas.close()
    with output.open("x", encoding="utf-8") as stream:
        json.dump(sheets, stream, ensure_ascii=False, default=str)


def display(value):
    if value is None or value == "":
        return "待确认"
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value
    raise IntakeError("草稿中的字段须为文字、数字或空值。")


def put(sheet, row, column, value):
    value = display(value)
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def write_draft(source, output):
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.keys() - {"details", "items"}:
        raise IntakeError("请提供草稿的资料和商品行。")
    details = data.get("details", {})
    items = data.get("items")
    if (not isinstance(details, dict) or details.keys() - dict(DRAFT_FIELDS).keys()
            or not isinstance(items, list) or not 0 < len(items) <= MAX_ROWS):
        raise IntakeError("请先提取至少一行商品，并检查草稿字段。")
    if any(not isinstance(row, dict) or row.keys() - dict(DRAFT_COLUMNS).keys() for row in items):
        raise IntakeError("草稿有无法识别的商品字段。")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "内部报价草稿"
    sheet.merge_cells("A1:I1")
    sheet["A1"] = "内部报价草稿｜核对商业信息后再出正式单据"
    sheet["A1"].font = Font(size=14, bold=True)
    sheet.row_dimensions[1].height = 26
    for row, (key, label) in enumerate(DRAFT_FIELDS, 3):
        sheet.cell(row, 1, label)
        sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=9)
        put(sheet, row, 2, details.get(key))
    widths = (30, 20, 17, 17, 12, 14, 14, 16, 24)
    for col, ((_, label), width) in enumerate(zip(DRAFT_COLUMNS, widths, strict=True), 1):
        cell = sheet.cell(10, col, label)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[cell.column_letter].width = width
    sheet.row_dimensions[10].height = 30
    for row, item in enumerate(items, 11):
        lines = 1
        for col, ((key, _), width) in enumerate(zip(DRAFT_COLUMNS, widths, strict=True), 1):
            cell = put(sheet, row, col, item.get(key))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            value = item.get(key)
            if isinstance(value, str) and value:
                display = sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                              for ch in value)
                lines = max(lines, math.ceil(display / (width * 0.92)))
        sheet.row_dimensions[row].height = max(22, lines * 14.5 + 6)
    sheet.freeze_panes = "A11"
    sheet.auto_filter.ref = f"A10:I{10 + len(items)}"
    # 独立 CLI（无引擎目录）内联的打印设置，与正式单据保持同一版式口径：
    # A4 竖版、一页宽、纵向允许分页、多页重复商品表头。
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = f"A1:I{sheet.max_row}"
    sheet.print_title_rows = "10:10"
    save_workbook(workbook, output)
    workbook.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "draft"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        operation = inspect_workbook if args.action == "inspect" else write_draft
        operation(args.source, args.output)
    except IntakeError as exc:
        parser.exit(1, str(exc) + "\n")
    except FileExistsError:
        parser.exit(1, "目标文件已存在，请选择新文件名。\n")
    except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError, ParseError):
        parser.exit(1, "无法读取或写入文件，请检查格式、路径和权限。\n")
    print(args.output)


if __name__ == "__main__":
    main()
