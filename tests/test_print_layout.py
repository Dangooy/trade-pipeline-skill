"""打印版式回归测试（纯虚构数据，隔离目录 fixtures）。

复现：正式 PI 的商品描述（品名 / 规格 / 货号 / 内袋装量）原先挤在 8 字符
宽的 A 列、无换行、行高 13pt，右侧的 Qty / Amount 列一有内容就把它截断。
本测试锁定修复后的行为：描述完整、自动换行、行高足够、数字列不被合并
覆盖、A4 竖版一页宽、多页重复商品表头，且公式与数值保持原样。
"""
import copy
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from workbuddy.scripts import documents as doc
from workbuddy.scripts import intake
from workbuddy.scripts.delivery import delivery_markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "workbuddy-print"
PRODUCT = ("description", "spec", "material", "finish")
A4 = 9  # openpyxl Worksheet.PAPERSIZE_A4

# 描述单元格 / 数字列 / 表头行关键字，按单据类型给出
LAYOUT = {
    "pi": {"desc_col": 1, "num_cols": (12, 13, 14, 15), "header": "Name of Commodity"},
    "ci": {"desc_col": 3, "num_cols": (14, 15, 16, 17), "header": "DESCRIPTIONS"},
    "pl": {"desc_col": 2, "num_cols": (3, 4, 5, 6, 7), "header": "Description"},
}


def fixture(count):
    return json.loads((FIXTURES / f"synthetic-{count}-items.json").read_text(encoding="utf-8"))


def description_of(item):
    """documents.write_formal 拼商品信息的方式，逐字符比对用。"""
    return " · ".join(item[key] for key in PRODUCT if key in item)


def with_actuals(data):
    """补一组纯虚构出货 / 包装资料，使 CI、PL 也能走正式版渲染入口。"""
    data = copy.deepcopy(data)
    data["details"].update({
        "ci_number": "CI-PRINT-TEST", "port_destination": "DEMO DESTINATION",
        "gross_kg": 120.0, "packing": "Fictional cartons on demo pallets",
        "pallets": 2, "measurement_m3": 1.06,
    })
    for key in ("ci_number", "port_destination", "gross_kg", "packing",
                "pallets", "measurement_m3"):
        data["evidence"][f"details.{key}"] = ["source", "Fictional shipment evidence"]
    for index, row in enumerate(data["items"], 1):
        row.update({
            "shipped_quantity": row["quantity"],
            "invoice_unit_price": row["unit_price"],
            "net_kg": row["quoted_weight_kg"],
            "cartons": index + 1,
        })
        for key in ("shipped_quantity", "invoice_unit_price", "net_kg", "cartons"):
            data["evidence"][f"items.{index}.{key}"] = [
                "source", "Fictional shipment evidence",
            ]
    return data


def assert_page(ws, *, last_col):
    """A4 竖版 / 一页宽 / 纵向可分页 / 打印区域覆盖全部内容 / 重复表头。"""
    assert ws.page_setup.paperSize == A4
    assert ws.page_setup.orientation == "portrait"
    assert ws.page_setup.fitToWidth == 1
    assert ws.page_setup.fitToHeight == 0
    # fitToPage 在 openpyxl 里是 proxy 属性，重新载入后 _parent 未绑定会抛错；
    # 文件里真正被 Excel 读取的是 sheetPr/pageSetUpPr 上的这个标记。
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_area, "必须显式设置打印范围"
    assert "$A$1:" in str(ws.print_area)
    assert str(ws.print_area).endswith(f"${ws.max_row}"), "打印区域要覆盖最后一行"
    assert ws.print_title_rows, "多页须重复商品表头"
    assert str(ws.print_title_rows).startswith("$")


def assert_long_description(ws, desc_col, expected, *, min_height):
    """商品描述逐字符完整、自动换行、行高足够、未被省略号或缩字号处理。"""
    hits = [
        c for row in ws.iter_rows() for c in row
        if isinstance(c.value, str) and c.value == expected
    ]
    assert hits, "商品描述必须完整写入（不能被截断）"
    for cell in hits:
        assert cell.alignment.wrap_text is True, "描述单元格须自动换行"
        assert not isinstance(cell, MergedCell)
        height = ws.row_dimensions[cell.row].height
        assert height and height >= min_height, f"行高不足：{height}"
        assert "…" not in cell.value and "..." not in cell.value
        # 没有靠大幅缩字号解决
        assert cell.font.size is None or cell.font.size >= 9


def assert_number_columns_intact(ws, rows, num_cols):
    """已有内容的数字 / 金额列不得被合并覆盖。"""
    merges = list(ws.merged_cells.ranges)
    for row in rows:
        for col in num_cols:
            cell = ws.cell(row, col)
            assert not isinstance(cell, MergedCell), (row, col, "数字列被合并覆盖")
            assert not any(
                m.min_row <= row <= m.max_row and m.min_col <= col <= m.max_col
                for m in merges
            ), (row, col, "数字列落在合并区内")


# ── 基线：旧 fixtures 确实存在缺陷 ────────────────────────────────

@pytest.mark.parametrize("count", [6, 10])
def test_original_fixture_still_shows_the_defect(count):
    path = FIXTURES / f"synthetic-{count}-items-original-layout.xlsx"
    wb = load_workbook(path)
    ws = wb.active
    desc = [c for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and c.value.startswith("Fictional flat washer")]
    assert desc, "复现样张应有商品描述行"
    cell = desc[0]
    assert cell.column == 1
    assert ws.column_dimensions["A"].width == 8
    assert cell.alignment.wrap_text is not True
    assert ws.row_dimensions[cell.row].height == 13
    assert ws.print_title_rows is None
    wb.close()


# ── 正式版渲染入口 write_formal（PI / CI / PL）────────────────────

@pytest.mark.parametrize("count", [6, 10])
@pytest.mark.parametrize("kind", ["pi", "ci", "pl"])
def test_formal_entrypoint_print_layout(tmp_path, count, kind):
    data = fixture(count) if kind == "pi" else with_actuals(fixture(count))
    path = tmp_path / f"{count}_{kind}.xlsx"
    doc.write_formal(path, data, f"PRINT-{count}", kind, 1)

    wb = load_workbook(path)
    ws = wb.active
    cfg = LAYOUT[kind]
    assert_page(ws, last_col=cfg["num_cols"][-1])

    expected = [description_of(item) for item in fixture(count)["items"]]
    for text in expected:
        assert_long_description(ws, cfg["desc_col"], text, min_height=45)

    # 表头行被设为重复标题行
    header_rows = [
        row[0].row for row in ws.iter_rows()
        if any(isinstance(c.value, str) and cfg["header"] in c.value for c in row)
    ]
    assert header_rows, "找不到商品表头行"
    assert str(int(header_rows[0])) in str(ws.print_title_rows)

    # 数字列仍保有数量 / 金额 / 公式，且未被合并
    desc_rows = [
        c.row for row in ws.iter_rows() for c in row
        if isinstance(c.value, str) and c.value in expected
    ]
    assert_number_columns_intact(ws, desc_rows, cfg["num_cols"])
    for r in desc_rows:
        assert ws.cell(r, cfg["num_cols"][0]).value is not None, "数量列丢失"
        amount = ws.cell(r, cfg["num_cols"][-1]).value
        if kind in ("pi", "ci"):
            assert isinstance(amount, str) and amount.startswith("="), "金额公式丢失"
            assert str(r) in amount, "金额公式未引用本行"

    # 标题 / 表头文字完整
    header_cell = ws.cell(header_rows[0], cfg["desc_col"])
    assert header_cell.value and cfg["header"] in str(header_cell.value)
    assert header_cell.alignment.wrap_text is True or kind == "pl"
    wb.close()


# ── 长编号在打印范围最后一列内换行（O5 / O7 行号浮动都要覆盖）──────

LONG_PI_NUMBER = "PI-PRINT-with-actuals-6"


@pytest.mark.parametrize("seller_address", ["", "Fictional Export Tower, Demo Port, Test Country"])
def test_formal_pi_long_number_wraps_in_print_area(tmp_path, seller_address):
    """长 PI 编号在 O 列（打印范围最后一列）内换行，不溢出到范围外的 P 列。

    编号所在行号随卖方信息浮动：无地址时业务接口生成在 O5，有地址时是
    模板默认的 O7 —— 一律按代码生成的实际行号校验。
    """
    data = fixture(6)
    data["details"]["pi_number"] = LONG_PI_NUMBER
    data["evidence"]["details.pi_number"] = ["source", "Fictional PI header layout regression"]
    if seller_address:
        data["details"]["seller_address"] = seller_address
        data["evidence"]["details.seller_address"] = ["source", "Synthetic print layout test"]
    path = tmp_path / "pi_long_number.xlsx"
    doc.write_formal(path, data, "PRINT-with-actuals-6", "pi", 1)

    wb = load_workbook(path)
    ws = wb.active
    hits = [c for row in ws.iter_rows() for c in row if c.value == LONG_PI_NUMBER]
    assert hits, "PI 编号必须完整写入（不能被截断）"
    cell = hits[0]
    # 原值、原坐标（O 列 = 15）；右侧 P 列不承接溢出
    assert cell.column == 15
    assert ws.cell(cell.row, 16).value is None
    # 在现有打印范围内自动换行，行高随内容抬高（至少容两行）
    assert cell.alignment.wrap_text is True, "编号单元格须自动换行"
    height = ws.row_dimensions[cell.row].height
    assert height and height >= 27, f"编号行高不足：{height}"
    assert cell.font.size is None or cell.font.size >= 9, "不得靠缩字号解决"
    # 打印范围仍止于 O 列
    assert "$O$" in str(ws.print_area) and "$P$" not in str(ws.print_area)
    assert_page(ws, last_col=15)
    wb.close()


def test_formal_pi_short_number_keeps_valid_layout(tmp_path):
    """短编号不受影响：换行设置无害，整版版式仍通过校验。"""
    data = fixture(6)
    path = tmp_path / "pi_short_number.xlsx"
    doc.write_formal(path, data, "PRINT-6", "pi", 1)
    wb = load_workbook(path)
    ws = wb.active
    hits = [c for row in ws.iter_rows() for c in row if c.value == "PI-PRINT-6"]
    assert hits and hits[0].column == 15
    assert_page(ws, last_col=15)
    wb.close()


# ── CI / 装箱单长编号在同一打印范围内换行（表头行号浮动都覆盖）────

LONG_CI_NUMBER = "CI-PRINT-with-actuals-6"
LONG_ORDER_NO = "ORDER-PRINT-with-actuals-6"


def _with_long_header(data, *, seller_address):
    """补长 CI / PI 编号（带 evidence）与可选的卖方地址，供 formal 入口用。"""
    data = copy.deepcopy(data)
    data["details"]["pi_number"] = LONG_PI_NUMBER
    data["details"]["ci_number"] = LONG_CI_NUMBER
    for key in ("pi_number", "ci_number"):
        data["evidence"][f"details.{key}"] = [
            "source", "Fictional header layout regression",
        ]
    if seller_address:
        data["details"]["seller_address"] = seller_address
        data["evidence"]["details.seller_address"] = [
            "source", "Synthetic print layout test",
        ]
    return data


@pytest.mark.parametrize(
    "seller_address", ["", "Fictional Export Tower, Demo Port, Test Country"],
)
def test_formal_ci_long_numbers_wrap_in_print_area(tmp_path, seller_address):
    """CI 表头 Q 列（打印范围最后一列）的三个长编号 / 标签在列内换行。

    CI 编号右对齐时开头被 P 列「号码NO.」挡住、相邻的 SALES CONTRACT NO.
    开头被裁、同一表头引用的长 PI 号顶到打印右边界：三者都要在 Q 列内
    自动换行并抬高行高。表头行号随卖方 / 买方信息浮动，按实际坐标校验。
    """
    data = _with_long_header(with_actuals(fixture(6)), seller_address=seller_address)
    path = tmp_path / "ci_long_numbers.xlsx"
    doc.write_formal(path, data, "PRINT-with-actuals-6", "ci", 1)

    wb = load_workbook(path)
    ws = wb.active
    for text in (LONG_CI_NUMBER, "SALES CONTRACT NO.", LONG_PI_NUMBER):
        hits = [c for row in ws.iter_rows() for c in row if c.value == text]
        assert hits, f"{text} 必须完整写入（不能被截断）"
        cell = hits[0]
        assert cell.column == 17, f"{text} 须留在 Q 列（打印范围最后一列）"
        assert cell.alignment.wrap_text is True, f"{text} 单元格须自动换行"
        height = ws.row_dimensions[cell.row].height
        assert height and height >= 27, f"{text} 行高不足：{height}"
        assert cell.font.size is None or cell.font.size >= 9, "不得靠缩字号解决"
    # 右对齐、号码标签、打印范围与整版版式保持原样
    ci_cell = [c for row in ws.iter_rows() for c in row
               if c.value == LONG_CI_NUMBER][0]
    assert ci_cell.alignment.horizontal == "right"
    assert ws.cell(ci_cell.row, 16).value == "号码NO."
    assert "$Q$" in str(ws.print_area) and "$R$" not in str(ws.print_area)
    assert_page(ws, last_col=17)
    wb.close()


@pytest.mark.parametrize(
    "seller_address", ["", "Fictional Export Tower, Demo Port, Test Country"],
)
def test_formal_pl_long_pi_number_wraps_in_print_area(tmp_path, seller_address):
    """装箱单 G 列（打印范围最后一列）的长 PI 号在列内换行，尾部不越界。"""
    data = _with_long_header(with_actuals(fixture(6)), seller_address=seller_address)
    path = tmp_path / "pl_long_pi_number.xlsx"
    doc.write_formal(path, data, "PRINT-with-actuals-6", "pl", 1)

    wb = load_workbook(path)
    ws = wb.active
    hits = [c for row in ws.iter_rows() for c in row if c.value == LONG_PI_NUMBER]
    assert hits, "PI 编号必须完整写入（不能被截断）"
    cell = hits[0]
    assert cell.column == 7, "编号须留在 G 列（打印范围最后一列）"
    assert ws.cell(cell.row, 6).value == "PI No.:"
    assert cell.alignment.wrap_text is True, "编号单元格须自动换行"
    height = ws.row_dimensions[cell.row].height
    assert height and height >= 27, f"编号行高不足：{height}"
    assert cell.font.size is None or cell.font.size >= 9, "不得靠缩字号解决"
    assert "$G$" in str(ws.print_area) and "$H$" not in str(ws.print_area)
    assert_page(ws, last_col=7)
    wb.close()


def test_formal_pl_order_no_fallback_wraps_in_print_area(tmp_path):
    """无 PI 号时走 Order No. 兼容路径，长订单号同样在 G 列内换行。

    兼容分支不能被长编号修复绕过：标签换为 Order No.:、编号取 order_no，
    仍在 G 列自动换行、行高足够，整版版式不变。
    """
    data = with_actuals(fixture(6))
    data["details"].pop("pi_number", None)
    data["evidence"].pop("details.pi_number", None)
    path = tmp_path / "pl_order_no.xlsx"
    doc.write_formal(path, data, LONG_ORDER_NO, "pl", 1)

    wb = load_workbook(path)
    ws = wb.active
    hits = [c for row in ws.iter_rows() for c in row if c.value == LONG_ORDER_NO]
    assert hits, "Order No. 编号必须完整写入（不能被截断）"
    cell = hits[0]
    assert cell.column == 7
    assert ws.cell(cell.row, 6).value == "Order No.:"
    assert cell.alignment.wrap_text is True, "编号单元格须自动换行"
    height = ws.row_dimensions[cell.row].height
    assert height and height >= 27, f"编号行高不足：{height}"
    assert_page(ws, last_col=7)
    wb.close()


# ── 内部工作稿渲染入口 write_draft ────────────────────────────────

@pytest.mark.parametrize("count", [6, 10])
@pytest.mark.parametrize("kind", ["pi", "ci", "pl"])
def test_internal_draft_print_layout(tmp_path, count, kind):
    data = fixture(count)
    path = tmp_path / f"draft_{count}_{kind}.xlsx"
    doc.write_draft(path, data, f"PRINT-{count}", kind, ["演示缺项"], 1)

    wb = load_workbook(path)
    ws = wb.active
    assert "INTERNAL DRAFT" in str(ws["A1"].value)
    assert_page(ws, last_col=ws.max_column)
    for item in data["items"]:
        for key in ("description", "spec"):
            hits = [c for row in ws.iter_rows() for c in row if c.value == item[key]]
            assert hits, f"{key} 须完整出现在内部工作稿"
            for cell in hits:
                assert cell.alignment.wrap_text is True
                assert ws.row_dimensions[cell.row].height >= 45
    # 缺项仍留待确认，不擅自补实际资料
    assert any("演示缺项" in str(c.value) for row in ws.iter_rows() for c in row)
    wb.close()


# ── 独立 CLI 的内部报价草稿 ──────────────────────────────────────

def test_intake_draft_print_layout(tmp_path):
    source = tmp_path / "draft.json"
    output = tmp_path / "intake_draft.xlsx"
    long_name = "Fictional flat washer for a long-print-column layout test, precision zinc-plated finish"
    source.write_text(json.dumps({
        "details": {"seller": "DEMO EXPORT LTD", "buyer": "DEMO IMPORT LTD"},
        "items": [{"description": long_name, "spec": "TEST-CODE-0001 · 6.4 × 17 × 3 mm · 500 pcs per inner bag"}],
    }, ensure_ascii=False), encoding="utf-8")
    intake.write_draft(source, output)

    wb = load_workbook(output)
    ws = wb.active
    assert_page(ws, last_col=9)
    assert ws.print_title_rows == "$10:$10"
    cell = [c for row in ws.iter_rows() for c in row if c.value == long_name][0]
    assert cell.alignment.wrap_text is True
    assert ws.row_dimensions[cell.row].height >= 45
    wb.close()


# ── 完整流程：普通工作稿 → 正式确认，缺实际资料仍待确认 ───────────

class PrintCase:
    def __init__(self, tmp_path, count):
        self.root = tmp_path
        self.count = count
        self.order = f"PRINT-DEMO-{count}"
        self.source = tmp_path / "fictional_source.xlsx"
        self.input = tmp_path / "order-input.json"
        from openpyxl import Workbook
        book = Workbook()
        book.active.title = "Quote"
        book.active.append(["Description", "Qty", "Unit", "Price"])
        for item in fixture(count)["items"]:
            book.active.append([item["description"], item["quantity"], item["unit"], item["unit_price"]])
        book.save(self.source)
        book.close()
        self.data = fixture(count)

    def call(self, action, documents, **kwargs):
        self.input.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        return doc.run(self.root, action, self.order, documents,
                       [self.source], self.input, **kwargs)


@pytest.mark.parametrize("count", [6, 10])
def test_document_entrypoints_draft_then_formal(tmp_path, count, monkeypatch):
    case = PrintCase(tmp_path, count)
    kinds = ("pi", "ci", "pl")

    draft = case.call("draft", kinds)
    assert draft["status"] == "committed"
    for kind in kinds:
        assert draft["documents"][kind]["file"]["status"] == "draft"
    # 缺实际出货 / 包装资料时，CI / PL 明确列出待确认项，不冒充正式单据
    assert draft["documents"]["ci"]["missing"]
    assert draft["documents"]["pl"]["missing"]
    assert not draft["documents"]["pi"]["missing"]

    review = case.call("review", kinds)
    token = review["review_token"]
    assert token
    monkeypatch.setattr(doc, "approve_on_desktop", lambda *_a, **_k: True)
    formal = case.call("formal", kinds, review_token=token)
    assert formal["documents"]["pi"]["file"]["status"] == "formal"
    assert formal["documents"]["ci"]["file"]["status"] == "draft"
    assert formal["documents"]["pl"]["file"]["status"] == "draft"

    # 首次交付链接机制原样：本次请求范围内每份 Excel 各一行
    links = delivery_markdown(formal, "formal", kinds)
    assert links.count("\n") + 1 == 3
    for kind in kinds:
        assert f"_{kind}.xlsx" in links

    # 三份产物都通过版式校验
    for kind in kinds:
        path = Path(formal["documents"][kind]["file"]["path"])
        wb = load_workbook(path)
        assert_page(wb.active, last_col=wb.active.max_column)
        wb.close()


# ── 打包覆盖清单必须带上共享版式模块 ──────────────────────────────

def test_build_manifest_carries_shared_layout_module():
    import ast
    build = (ROOT / "scripts/build_workbuddy.py").read_text(encoding="utf-8")
    tree = ast.parse(build)
    updates = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ENGINE_UPDATES" for t in node.targets
        ):
            updates = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert updates is not None
    for required in (
        "trade_pipeline/writers/base_writer.py",
        "trade_pipeline/writers/pi_writer.py",
        "trade_pipeline/writers/ci_writer.py",
        "trade_pipeline/writers/pl_writer_lite.py",
    ):
        assert required in updates, f"打包后版式会回退：{required} 未覆盖"
