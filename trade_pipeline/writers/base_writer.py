"""
writers/base_writer.py — Writer 公共基类 + 共享辅助函数

所有 Writer（Quote/PI/CI/PL）继承此基类，保持统一接口。
共享的 openpyxl cell/merge/border 辅助函数也集中在此。
"""
import math
import unicodedata

from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

FONT_NAME = "Calibri"

# 公式注入（CSV/Formula injection）净化：openpyxl 会把以这些字符开头的
# 字符串当作 Excel 公式写入（data_type='f'），打开时可能触发命令/取数攻击
# （如 =cmd|'/c calc'!A1、=HYPERLINK(...)）。对来自输入数据的字符串值，
# 前置一个单引号强制转为文本，Excel 显示时不带该引号。
# 我们“主动写的公式”（金额 =SUM/=.. ）通过 formula=True 显式豁免。
_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def _sanitize(value, formula: bool):
    """对字符串输入做公式注入净化；formula=True 表示这是刻意写的公式，原样保留。

    非字符串（数字/日期/None）不处理。以触发字符开头的字符串前置 `'`。
    """
    if formula or not isinstance(value, str):
        return value
    if value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def sc(ws, r, c, value=None, font=None, align=None, border=None, num_fmt=None,
       formula=False):
    """Set cell: write value and apply styles to a single cell.

    formula=True：value 是刻意写入的 Excel 公式（如金额 =SUM/=..），
    跳过公式注入净化。默认 False（把来自输入数据的可疑字符串转为文本）。
    """
    cell = ws.cell(row=r, column=c)
    if value is not None:
        cell.value = _sanitize(value, formula)
    if font:
        cell.font = font
    if align:
        cell.alignment = align
    if border:
        cell.border = border
    if num_fmt:
        cell.number_format = num_fmt
    return cell


def mc(ws, r1, c1, r2, c2, value=None, font=None, align=None, formula=False):
    """Merge cells and set value/style on the top-left cell.

    formula=True 时跳过公式注入净化（默认净化，见 _sanitize）。
    """
    if not (r1 == r2 and c1 == c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    cell = ws.cell(row=r1, column=c1)
    if value is not None:
        cell.value = _sanitize(value, formula)
    if font:
        cell.font = font
    if align:
        cell.alignment = align
    return cell


def brd(top=None, bottom=None, left=None, right=None):
    """Create a Border with named side styles (e.g. 'thin', 'medium')."""
    def _side(x):
        return Side(style=x) if x else Side(style=None)
    return Border(top=_side(top), bottom=_side(bottom), left=_side(left), right=_side(right))


def rh(ws, r, pts):
    """Set row height in points."""
    ws.row_dimensions[r].height = pts


# ── 打印版式共享函数（正式 PI/CI/PL 与内部工作稿共用）─────────────
# 修复目标：商品描述（品名 / 规格 / 货号 / 包装）原先挤在窄列里，右侧的
# 数量或金额列一有内容就把它截断。做法是让描述区用满可用列宽、自动换行、
# 给足行高；页面统一 A4 竖版、一页宽、纵向允许合理分页、多页重复商品表头。
#
# 约束：这些函数只调整对齐、行高与页面级设置，绝不改动任何单元格的值、
# 公式、数字格式，也不合并覆盖已含数据的邻列（合并范围由各 Writer 指定，
# 只跨本来就空的占位列）。


def _display_units(text: str) -> float:
    """按显示宽度折算字符数：东亚全角 / 宽字符算 2，其余算 1。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def _available_width(ws, first_col: int, last_col: int) -> float:
    """[first_col, last_col] 区间的可用列宽（Excel 列宽单位 ≈ 字符数）。"""
    total = 0.0
    for col in range(first_col, last_col + 1):
        dim = ws.column_dimensions.get(get_column_letter(col))
        width = getattr(dim, "width", None) if dim is not None else None
        total += float(width) if width else 13.0  # openpyxl 未显式设置时默认 13
    return total


def wrapped_row_height(ws, text, first_col: int = 1, last_col: int = 1, *,
                       font_size: float = 10.0, min_pts: float = 15.0,
                       fill_ratio: float = 0.92, pad_pts: float = 6.0) -> float:
    """估算自动换行单元格所需行高（pt），宁高勿截。

    Excel 对合并单元格不会自动调整行高，必须由出表方显式给出；否则即使
    wrap_text 开着、行高仍是一行，长品名 / 规格 / 货号 / 包装依旧被裁掉。
    按可用列宽折算行数（含显式换行），不缩字号、不用省略号。
    """
    line_pts = font_size * 1.45
    capacity = max(8.0, _available_width(ws, first_col, last_col) * fill_ratio)
    lines = 0
    for paragraph in ("" if text is None else str(text)).split("\n"):
        lines += max(1, math.ceil(_display_units(paragraph) / capacity))
    return max(min_pts, round(lines * line_pts + pad_pts, 1))


def set_print_layout(ws, last_col: int, *, title_rows: str | None = None,
                     orientation: str = "portrait", margins=None) -> None:
    """统一打印设置：A4、竖版、一页宽、纵向允许分页、多页重复商品表头。

    只写页面级设置，不触碰任何单元格值 / 公式 / 数字格式 / 已有合并。
    fitToPage 必须同时写在 pageSetup 与 sheetPr/pageSetUpPr 上，Excel 才
    真正按"一页宽"缩放；只写前者会被 Excel 忽略。
    """
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = orientation
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    props = ws.sheet_properties.pageSetUpPr
    if props is None:
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    else:
        props.fitToPage = True
    if margins is not None:
        ws.page_margins = margins
    ws.print_area = f"A1:{get_column_letter(last_col)}{max(1, ws.max_row)}"
    if title_rows:
        ws.print_title_rows = title_rows


class BaseWriter:
    """Writer 统一基类"""

    def __init__(self, model, config: dict | None = None):
        """
        参数:
            model: OrderModel 实例（必须已 resolve）
            config: 完整 config dict（PLWriter 需要）
        """
        self.model = model
        self.config = config or {}

        if model.resolved:
            self.seller = model.resolved.seller
            self.buyer = model.resolved.buyer
            self.terms = model.resolved.terms
        else:
            self.seller = {}
            self.buyer = {}
            self.terms = {}

    def write(self, output_path: str, **kwargs) -> dict:
        """
        生成文档。子类必须实现。

        返回:
            dict — 生成结果摘要
        """
        raise NotImplementedError(f"{self.__class__.__name__}.write() 未实现")

    # ── 样式辅助方法 ──

    @staticmethod
    def fnt(size=10, bold=False, color="222222"):
        return Font(name=FONT_NAME, size=size, bold=bold, color=color)

    @staticmethod
    def aln(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    @staticmethod
    def fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)

    @staticmethod
    def thin(color="E0E0E0"):
        return Side(style="thin", color=color)

    @staticmethod
    def med(color="1F3864"):
        return Side(style="medium", color=color)
