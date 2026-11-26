"""Plan and maintain the requested documents for one WorkBuddy order."""
import argparse
import json
import math
import re
import sys
import time
from datetime import date
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

if __package__:
    from .actuals import manual_facts, normalize_unit, verified_data
    from .approval import ApprovalUnavailable, approve_on_desktop
    from .order_store import OrderStore, OrderStoreError, digest, file_digest, json_bytes
    from .business import SetupError, workspace_lock
    from .delivery import delivery_markdown
    from .formal import DOCUMENT_NAMES, EMPTY_TERM, PLACEHOLDER, missing_terms
    from .intake import put
    from .workbook_output import save_workbook
else:
    from actuals import manual_facts, normalize_unit, verified_data
    from approval import ApprovalUnavailable, approve_on_desktop
    from order_store import OrderStore, OrderStoreError, digest, file_digest, json_bytes
    from business import SetupError, workspace_lock
    from delivery import delivery_markdown
    from formal import DOCUMENT_NAMES, EMPTY_TERM, PLACEHOLDER, missing_terms
    from intake import put
    from workbook_output import save_workbook

REVIEW_SECONDS = 600
KEEP_CURRENT_STATE = object()
DETAILS = {
    "seller": "卖方英文名", "seller_address": "卖方地址",
    "buyer": "买方英文名", "buyer_address": "买方地址",
    "currency": "币种", "price_unit": "计价单位", "payment": "付款条件",
    "delivery": "贸易条件及地点", "lead_time": "交期",
    "port_loading": "装运地", "port_destination": "目的地", "date": "单据日期",
    "pi_number": "PI 编号", "ci_number": "CI 编号",
    "bank_name": "银行名称", "bank_account": "收款账号", "swift": "SWIFT",
    "gross_kg": "实际总毛重 (kg)", "pallets": "实际托盘数",
    "measurement_m3": "实际总体积 (m³)", "packing": "实际包装说明",
}
ITEMS = {
    "description": "品名", "spec": "规格", "material": "材质", "finish": "表面处理",
    "quantity": "报价数量", "unit": "单位", "unit_price": "报价单价",
    "quoted_weight_kg": "报价净重 (kg)", "shipped_quantity": "实际出货数量",
    "invoice_unit_price": "本单开票单价", "net_kg": "实际净重 (kg)", "cartons": "实际箱数",
}
NUMBERS = {
    "quantity", "unit_price", "quoted_weight_kg", "shipped_quantity",
    "invoice_unit_price", "net_kg", "cartons", "gross_kg", "pallets", "measurement_m3",
}
COMMON = ("seller", "buyer", "payment", "delivery", "port_loading", "date")
PARTIES = ("seller", "seller_address", "buyer", "buyer_address")
TERMS = ("payment", "delivery", "port_loading", "date")
DOC_DETAILS = {
    "pi": (*PARTIES, *TERMS, "lead_time", "currency", "price_unit", "pi_number",
           "bank_name", "bank_account", "swift"),
    "ci": (*PARTIES, *TERMS, "port_destination", "currency", "price_unit",
           "ci_number", "pi_number", "gross_kg", "pallets", "bank_name", "bank_account", "swift"),
    "pl": (*PARTIES, *TERMS, "port_destination", "pi_number", "gross_kg", "pallets",
           "measurement_m3", "packing"),
}
DOC_ITEMS = {
    "pi": ("quantity", "unit", "unit_price", "quoted_weight_kg"),
    "ci": ("quantity", "unit", "shipped_quantity", "invoice_unit_price", "net_kg"),
    "pl": ("quantity", "unit", "shipped_quantity", "net_kg", "cartons"),
}
PRODUCT = ("description", "spec", "material", "finish")


class DocumentError(Exception):
    pass


def parse_snapshot(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"details", "items", "evidence"}:
        raise DocumentError("订单资料须包含 details、items 和 evidence。")
    details, items, evidence = data["details"], data["items"], data["evidence"]
    if (not isinstance(details, dict) or not isinstance(items, list) or not 0 < len(items) <= 5000
            or not isinstance(evidence, dict)):
        raise DocumentError("订单资料没有有效的商品行或出处。")
    valid_evidence = set()
    sections = [("details", details, DETAILS)]
    sections.extend((f"items.{row}", item, ITEMS) for row, item in enumerate(items, 1))
    for prefix, fields, allowed in sections:
        if not isinstance(fields, dict) or fields.keys() - allowed.keys():
            raise DocumentError(f"{prefix} 含有未识别字段。")
        for field, value in fields.copy().items():
            if value is None or value == "":
                del fields[field]
                continue
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if field in NUMBERS:
                if not number or not math.isfinite(value) or value < 0:
                    raise DocumentError(f"{prefix}.{field} 须为有效的非负数。")
                if field in ("cartons", "pallets") and int(value) != value:
                    raise DocumentError(f"{prefix}.{field} 须为整数。")
            elif not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise DocumentError(f"{prefix}.{field} 须为有效文本。")
            key = f"{prefix}.{field}"
            entry = evidence.get(key)
            if (not isinstance(entry, list) or len(entry) != 2
                    or entry[0] not in ("source", "extracted", "confirmed")
                    or not isinstance(entry[1], str) or not entry[1].strip()
                    or len(entry[1]) > 500):
                raise DocumentError(f"{key} 缺少来源和确认状态。")
            valid_evidence.add(key)
    if evidence.keys() - valid_evidence:
        raise DocumentError("有来源记录指向空字段或不存在的商品行。")
    return data


def values(data, prefix, fields, *, formal=False):
    if not formal:
        return fields.copy()
    return {
        key: value for key, value in fields.items()
        if data["evidence"][f"{prefix}.{key}"][0] != "extracted"
        and not (isinstance(value, str) and (PLACEHOLDER.search(value)
                                             or EMPTY_TERM.fullmatch(value.strip())))
    }


def calculate_amount(details, row, kind):
    from trade_pipeline.models.amounts import compute_amount

    quantity_key, price_key, weight_key = {
        "pi": ("quantity", "unit_price", "quoted_weight_kg"),
        "ci": ("shipped_quantity", "invoice_unit_price", "net_kg"),
    }[kind]
    unit = normalize_unit(row.get("unit"))
    currency = details.get("currency", "").strip().upper()
    basis = details.get("price_unit", "").strip().upper()
    per_thousand = re.fullmatch(
        r"([A-Z]{3})(?:\s*/\s*|\s+PER\s+)(?:1,000|1000)\s*(?:PCS?|PIECES)", basis,
    )
    if per_thousand:
        basis = f"{per_thousand[1]}/MPCS"
    basis_currency, _, key = basis.partition("/")
    unit_for_basis = {"PC": "pcs", "PCS": "pcs", "MPCS": "pcs", "KG": "kgs", "KGS": "kgs"}
    if (not re.fullmatch(r"[A-Z]{3}", currency) or currency != basis_currency
            or key not in {*unit_for_basis, "TON"} or not unit):
        return None
    quantity, price, weight = (row.get(key) for key in (quantity_key, price_key, weight_key))
    if (quantity is None or quantity <= 0 or price is None
            or (key == "TON" and weight is None)
            or (key != "TON" and unit != unit_for_basis[key])):
        return None
    amount = compute_amount(basis, quantity, weight, price)
    return amount if math.isfinite(amount) else None


def fields_for(data, kind, formal):
    details = values(data, "details", data["details"], formal=formal)
    keys = set((*PRODUCT, *DOC_ITEMS[kind]))
    rows = [
        {key: value for key, value in values(data, f"items.{number}", item, formal=formal).items()
         if key in keys}
        for number, item in enumerate(data["items"], 1)
    ]
    return {key: details[key] for key in DOC_DETAILS[kind] if key in details}, rows


def readiness(data, kind):
    details, rows = fields_for(data, kind, True)
    required = list(COMMON)
    if kind != "pl":
        required += ["bank_name", "bank_account", "swift"]
    if kind != "pi":
        required += ["port_destination", "gross_kg"]
    if kind == "pl":
        required += ["packing"]
    missing = [DETAILS[key] for key in required if key not in details]
    for key, label in (("payment", "付款条款"), ("delivery", "交货条款")):
        if key in details and label in missing_terms(details):
            missing.append(label)
    if kind != "pl" and "swift" in details and not re.fullmatch(
        r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?", details["swift"].upper()
    ):
        missing.append("SWIFT 格式")
    for key in ("ci_number", "pi_number"):
        if key in details and not re.fullmatch(r"[\w-]{1,31}", details[key]):
            missing.append(f"{DETAILS[key]}格式")
    try:
        if "date" in details:
            date.fromisoformat(details["date"])
    except ValueError:
        missing.append("日期格式（YYYY-MM-DD）")
    if kind == "ci" and "ci_number" not in details:
        missing.append("实际开票编号")
    units = {normalize_unit(row.get("unit")) for row in rows}
    for index, row in enumerate(rows, 1):
        required_row = ["description", "unit"]
        if kind != "pi":
            required_row += ["shipped_quantity", "net_kg"]
        if kind == "pl":
            required_row += ["cartons"]
        absent = [ITEMS[key] for key in required_row if key not in row]
        if kind != "pi" and "shipped_quantity" in row and row["shipped_quantity"] <= 0:
            absent.append("实际出货数量须大于零")
        quantity = row.get("quantity" if kind == "pi" else "shipped_quantity")
        if normalize_unit(row.get("unit")) == "pcs" and quantity is not None and int(quantity) != quantity:
            absent.append("件数须为整数")
        if kind == "pl" and row.get("cartons") == 0:
            absent.append("实际箱数须大于零")
        if kind != "pl" and calculate_amount(details, row, kind) is None:
            absent.append("金额待核算（核对数量、重量、价格、币种和计价单位）")
        if absent:
            missing.append(f"第 {index} 项：" + "、".join(absent))
    if len(units) != 1 or None in units:
        missing.append("商品数量单位需要明确且一致")
    if kind != "pi" and "gross_kg" in details and details["gross_kg"] < sum(
        row.get("net_kg", 0) for row in rows
    ) - 1e-8:
        missing.append("实际总毛重小于已知净重之和，请核对")
    return missing


def draft_fields(kind):
    return (
        tuple(key for key in DOC_DETAILS[kind] if key != "bank_account"),
        (*PRODUCT, *DOC_ITEMS[kind]),
    )


def draft_pending(data, kind):
    """Summarize the draft fields that are still unverified, including optional fields."""
    details, rows = fields_for(data, kind, True)
    detail_fields, item_fields = draft_fields(kind)
    pending = {
        key: DETAILS[key] for key in detail_fields if key not in details
    }
    pending.update({
        key: ITEMS[key] for key in item_fields if any(key not in row for row in rows)
    })
    priority = ("price_unit", "unit_price", "invoice_unit_price",
                "seller_address", "buyer_address", "description", "spec")
    fields = [pending[key] for key in dict.fromkeys((*priority, *pending)) if key in pending]
    return {
        "fields": fields,
        "amount_pending": kind != "pl" and any(
            calculate_amount(details, row, kind) is None for row in rows
        ),
    }


def write_draft(path, data, order, kind, missing, version):
    # 与 write_formal 一样延迟导入：技能脚本以 -I 独立运行，引擎目录由
    # main() 在解析参数后才加入 sys.path。
    from trade_pipeline.writers.base_writer import (
        set_print_layout, wrapped_row_height,
    )

    details, rows = fields_for(data, kind, False)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = kind.upper() + " DRAFT"
    sheet["A1"] = f"{kind.upper()} · INTERNAL DRAFT / 内部工作稿 · 待确认 · Rev {version}"
    workbook.properties.revision = str(version)
    sheet["A1"].font = Font(bold=True, size=15, color="9C0006")
    put(sheet, 2, 1, "订单")
    put(sheet, 2, 2, order)
    fields, columns = draft_fields(kind)
    for index, key in enumerate(fields, 3):
        put(sheet, index, 1, DETAILS[key])
        put(sheet, index, 2, details.get(key))
        if key in details:
            state, source = data["evidence"][f"details.{key}"]
            put(sheet, index, 3, f"{state} · {source}")
    header = len(fields) + 4
    include_amount = kind != "pl"
    labels = [ITEMS[key] for key in columns]
    if kind != "pi":
        labels[columns.index("quantity")] = "报价数量（仅参考）"
    if include_amount:
        labels.append("金额")
    labels.append("来源（内部核对）")
    # 品名/规格给宽列，数字列收窄，来源列保留足够宽度。原先所有列一律 27
    # 太宽，A4 竖版一页宽会被大幅缩印；长品名靠自动换行 + 行高显示完整。
    widths = [30 if key in ("description", "spec") else 13 for key in columns]
    if include_amount:
        widths.append(14)
    widths.append(46)
    header_height = 22
    for col, (label, width) in enumerate(zip(labels, widths, strict=True), 1):
        cell = put(sheet, header, col, label)
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(col)].width = width
        header_height = max(header_height, wrapped_row_height(
            sheet, label, col, col, font_size=10))
    sheet.row_dimensions[header].height = header_height
    amounts = []
    verified_details, verified_rows = fields_for(data, kind, True)
    for number, row in enumerate(rows, 1):
        for col, key in enumerate(columns, 1):
            cell = put(sheet, header + number, col, row.get(key))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        if include_amount:
            # An unverified extraction may be shown, but can't silently produce a verified amount.
            amount = calculate_amount(verified_details, verified_rows[number - 1], kind)
            amounts.append(amount)
            cell = put(sheet, header + number, len(columns) + 1,
                       "待核算" if amount is None else amount)
            cell.number_format = "#,##0.00"
        sources = [
            f"{ITEMS[key]}: {' · '.join(data['evidence'][f'items.{number}.{key}'])}"
            for key in columns if key in row
        ]
        put(sheet, header + number, len(labels), "\n".join(sources)).alignment = Alignment(
            wrap_text=True, vertical="top",
        )
        # 行高取"来源列"与所有商品/数字列换行需求的最大值，长品名、规格、
        # 货号、包装信息都能完整显示，不靠省略号或缩字号。
        height = max(22, len(sources) * 14)
        for col, key in enumerate(columns, 1):
            value = row.get(key)
            if value is not None:
                height = max(height, wrapped_row_height(
                    sheet, value, col, col, font_size=10, min_pts=15))
        sheet.row_dimensions[header + number].height = height
    footer = header + len(rows) + 1
    if include_amount:
        put(sheet, footer, 1, "合计")
        total = "待核算" if None in amounts else sum(amounts)
        put(sheet, footer, len(columns) + 1, total).number_format = "#,##0.00"
    else:
        put(sheet, footer, 1, "实际合计")
        for key in ("shipped_quantity", "net_kg", "cartons"):
            known = [row.get(key) for row in verified_rows]
            total = None if None in known else sum(known)
            put(sheet, footer, columns.index(key) + 1, total)
    for index, item in enumerate(missing, footer + 2):
        put(sheet, index, 1, item)
    sheet.freeze_panes = f"A{header + 1}"
    sheet.auto_filter.ref = f"A{header}:{get_column_letter(len(labels))}{footer - 1}"
    set_print_layout(sheet, len(labels), title_rows=f"{header}:{header}")
    save_workbook(workbook, path)
    workbook.close()


def write_formal(path, data, order, kind, version):
    from trade_pipeline.models.order_model import (
        DerivedData, OrderInfo, OrderItem, OrderModel, OrderRefs, ResolvedEntities,
    )
    from trade_pipeline.writers.ci_writer import CIWriter
    from trade_pipeline.writers.pi_writer import PIWriter
    from trade_pipeline.writers.pl_writer_lite import PackingLine, PLWriterLite

    details, rows = fields_for(data, kind, True)
    items = []
    for i, row in enumerate(rows, 1):
        name = " · ".join(row[key] for key in PRODUCT if key in row)
        items.append(OrderItem(
            i, OrderItem.generate_uuid(), None, None, name, name,
            row["quantity" if kind == "pi" else "shipped_quantity"], normalize_unit(row["unit"]),
            weight_kg=row.get("quoted_weight_kg" if kind == "pi" else "net_kg"),
            unit_price=row.get("unit_price" if kind == "pi" else "invoice_unit_price"),
        ))
    quote_ref = details.get("pi_number", f"PI-{order}" if kind == "pi" else "")
    net_weight = sum(item.weight_kg for item in items) if kind != "pi" else None
    model = OrderModel(
        OrderRefs("order", "order", "order"),
        OrderInfo(
            order, "washers_mar" if items[0].unit == "tons" else "standard",
            "", quote_ref, details.get("ci_number", ""), details["date"],
            details.get("currency", "").strip().upper(), details.get("price_unit", "").strip().upper(),
        ),
        items,
        DerivedData(total_qty=sum(item.quantity for item in items),
                    port_of_loading=details["port_loading"],
                    port_of_destination=details.get("port_destination"),
                    total_net_weight=net_weight, total_gross_weight=details.get("gross_kg"),
                    pallet_count=details.get("pallets")),
        resolved=ResolvedEntities(
            {"name_en": details["seller"], "address": details.get("seller_address", "")},
            {"name_en": details["buyer"], "address": details.get("buyer_address", ""),
             "address_lines": [details["buyer_address"]] if "buyer_address" in details else []},
            {key: details[key] for key in ("payment", "delivery", "lead_time") if key in details},
            {field: details[key] for field, key in
             (("name", "bank_name"), ("account_no", "bank_account"), ("swift", "swift"))
             if key in details},
        ),
    )
    def save_final(workbook, destination):
        workbook.properties.revision = str(version)
        workbook.active.oddFooter.right.text = f"Revision {version}"
        save_workbook(workbook, destination)
        workbook.close()

    if kind == "pi":
        PIWriter(model).write(path, quantity_unit=items[0].unit, workbook_saver=save_final)
    elif kind == "ci":
        CIWriter(model).write(path, verified_shipment=True, workbook_saver=save_final)
    else:
        lines = [
            PackingLine(item.description, "", item.quantity, item.weight_kg,
                        row["cartons"], item.weight_kg / row["cartons"])
            for item, row in zip(items, rows, strict=True)
        ]
        summary = {
            "total_cartons": sum(line.cartons for line in lines),
            "total_pcs": model.derived.total_qty,
            "total_net_weight": net_weight,
            "total_gross_weight": details["gross_kg"],
            "total_pallets": details.get("pallets"),
            "total_measurement_m3": details.get("measurement_m3"),
            "packing_text": details["packing"],
        }
        PLWriterLite(model).write(path, actual_packing=(lines, summary), workbook_saver=save_final)


def signature(data, kind, status):
    details, rows = fields_for(data, kind, status == "formal")
    if status == "formal" and kind != "pi":
        for row in rows:
            row.pop("quantity", None)
    evidence = data["evidence"]
    keys = [f"details.{key}" for key in details]
    keys += [f"items.{row}.{key}" for row, fields in enumerate(rows, 1) for key in fields]
    return digest(json_bytes([details, rows, {key: evidence[key] for key in keys}]))


def confirm_actuals(store, raw, facts, identifier, source_hashes, snapshot):
    if not identifier:
        raise DocumentError("没有需由本人核对的实际开票、出货或包装数据。")
    if store.manual_verified(identifier):
        return {"order": store.order, "status": "actuals_verified"}
    fields = facts["fields"]
    summaries = [
        f"{DETAILS[key]}：{fields[f'details.{key}']}"
        for key in DETAILS if f"details.{key}" in fields
    ]
    for index, row in enumerate(raw["items"], 1):
        selected = [f"{ITEMS[key]}：{fields[f'items.{index}.{key}']}"
                    for key in ITEMS if f"items.{index}.{key}" in fields]
        if selected:
            summaries.append(f"第 {index} 项 {row.get('description', '')} "
                             f"{row.get('spec', '')} · " + "；".join(selected))
    message = (f"订单：{store.order}\n请本人对照实际开票、出货或称重记录核对。"
               "如果仅有报价请点取消。此操作只核实资料。\n" + "\n".join(summaries))
    if len(message) > 1800:
        raise DocumentError("待人工核对的实际数据较多，请提供带商品行的实际出货或装箱表。")
    try:
        approved = approve_on_desktop(message, verifying_actuals=True)
    except ApprovalUnavailable as exc:
        raise DocumentError(str(exc)) from exc
    if not approved:
        raise DocumentError("实际资料未确认。当前成果保持原样。")
    verify_inputs(store, source_hashes, snapshot, raw)
    store.confirm_manual(identifier)
    return {"order": store.order, "status": "actuals_verified"}


def verify_inputs(store, sources, snapshot, raw, state_hash=KEEP_CURRENT_STATE):
    if any(file_digest(Path(path)) != previous for path, previous in sources.items()):
        raise DocumentError("来源文件已变化，请重新核对。")
    if snapshot and parse_snapshot(snapshot) != raw:
        raise DocumentError("订单资料已变化，请重新核对。")
    if state_hash is not KEEP_CURRENT_STATE and store.read()[0] != state_hash:
        raise DocumentError("订单已变化，请重新核对。")


def current_receipt(store, current, pending, snapshot, documents, expected_sources):
    if not current:
        return {"order": store.order, "status": "not_committed", "pending_attempts": pending}
    sources = current["sources"]
    source_matches = all(Path(path).is_file() and file_digest(Path(path)) == issued
                         for path, issued in sources.items())
    raw = current["data"]
    facts = manual_facts(raw)
    attestation = digest(json_bytes(facts)) if facts else None
    accepted, _ = verified_data(raw, sources, store.manual_verified(attestation)) if source_matches else ({}, [])
    files = {}
    blocked = []
    for kind, record in current.get("artifacts", {}).items():
        if source_matches:
            try:
                store.check_file(kind, record)
                if record["status"] == "formal" and readiness(accepted, kind):
                    blocked.append(kind)
                else:
                    files[kind] = record
            except OrderStoreError:
                blocked.append(kind)
        else:
            blocked.append(kind)
    receipt = current.get("receipt", {})
    requested = set(receipt.get("requested", ()))
    request_matches = (
        (not snapshot or parse_snapshot(snapshot) == raw)
        and (not documents or set(documents) <= requested)
        and all(str(path.resolve(strict=True)) in sources for path in expected_sources)
    )
    status = "committed"
    if blocked or not request_matches:
        status = "blocked"
    elif pending:
        status = "pending"
    return {
        "order": store.order,
        "status": status,
        "pending_attempts": pending,
        "source_matches": source_matches,
        "request_matches": request_matches,
        "blocked_documents": blocked,
        "receipt": receipt,
        "documents": files,
        "draft_pending": {
            kind: draft_pending(accepted, kind) for kind, record in files.items()
            if status == "committed" and record["status"] == "draft"
        },
    }


def current_delivery(store, current, pending, snapshot, documents, sources, delivery_files):
    scope = set(documents or ())
    provided = set(delivery_files)
    if not scope or len(delivery_files) != len(scope) or len(provided) != len(scope):
        raise DocumentError("请为本次交付的每种单据提供一个已提交文件。")
    checked = current_receipt(store, current, pending, snapshot, None, sources)
    outcome = {"order": store.order, "status": checked["status"]}
    if checked["status"] != "committed":
        return outcome
    files = {kind: record for kind, record in checked["documents"].items() if kind in scope}
    if set(files) != scope or {Path(record["path"]) for record in files.values()} != provided:
        return {**outcome, "status": "blocked", "request_matches": False}
    return {
        **outcome,
        "receipt": {"action": "delivery", "requested": list(files), "changed": []},
        "documents": files,
        "draft_pending": {
            kind: note for kind, note in checked["draft_pending"].items() if kind in scope
        },
    }


def run(root, action, order, documents, sources=(), snapshot=None, review_token=None, sync=False,
        *, delivery_files=()):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", order):
        raise DocumentError("订单号须为 1–48 位字母、数字、短横线或下划线。")
    store = OrderStore(root, order)
    state_hash, current, pending = store.read()
    if action == "status":
        return current_receipt(store, current, pending, snapshot, documents, sources)
    if action == "delivery":
        return current_delivery(store, current, pending, snapshot, documents, sources, delivery_files)
    if action == "snapshot":
        if not current:
            raise DocumentError("该订单没有已保存的共享资料。")
        return current["data"]
    if snapshot is None and not current:
        raise DocumentError("请先读取业务附件并提供一次共享订单资料。")
    raw = parse_snapshot(snapshot) if snapshot else current["data"]
    original_sources = current.get("sources", {})
    # A changed original requires a refreshed extraction and an explicitly supplied source.
    if sources and snapshot is None:
        raise DocumentError("替换来源文件时，请同时提供重新核对后的共享订单资料。")
    supplied = {str(path.resolve(strict=True)) for path in sources}
    source_paths = set(original_sources) | supplied
    source_hashes = {path: file_digest(Path(path)) for path in sorted(source_paths)}
    if any(source_hashes[path] != old for path, old in original_sources.items() if path not in supplied):
        raise DocumentError("来源文件已变化，请重新读取并提供最新共享资料。")
    if not source_hashes:
        raise DocumentError("请提供至少一个业务来源文件。")
    facts = manual_facts(raw)
    attestation = digest(json_bytes(facts)) if facts else None
    if action == "confirm-actuals":
        return confirm_actuals(store, raw, facts, attestation, source_hashes, snapshot)
    manual_verified = store.manual_verified(attestation)
    data, rejected = verified_data(raw, source_hashes, manual_verified)
    artifacts = current.get("artifacts", {}).copy()
    stale = {
        kind for kind, record in artifacts.items()
        if signature(data, kind, record["status"]) != record["signature"]
    }
    selected = set(documents or ())
    if action == "check":
        selected = selected or set(DOCUMENT_NAMES)
    if sync:
        selected |= stale
    elif action in ("draft", "formal") and stale - selected:
        raise DocumentError("本次修改还影响已交付单据，确认同步范围后用 --sync 一起更新。")
    selected = tuple(kind for kind in DOCUMENT_NAMES if kind in selected)
    if not selected:
        raise DocumentError("请指定用户需要的单据。")
    if action != "check":
        for kind in selected:
            if kind in artifacts:
                store.check_file(kind, artifacts[kind])
    checks = {kind: readiness(data, kind) for kind in selected}
    ready = tuple(kind for kind in selected if not checks[kind])
    results = {}
    for kind in selected:
        details, rows = fields_for(data, kind, True)
        amounts = [calculate_amount(details, row, kind) for row in rows] if kind != "pl" else []
        actual_fields = DOC_ITEMS[kind]
        results[kind] = {
            "missing": checks[kind], "can_issue": kind in ready,
            "adopted": {key: value for key, value in details.items() if key != "bank_account"},
            "items": [
                {key: value for key, value in row.items() if key in (*PRODUCT, *actual_fields)}
                for row in rows
            ],
            "amount": None if not amounts or None in amounts else sum(amounts),
        }
    binding = [str(root), order, selected, ready, raw, source_hashes, state_hash, manual_verified]
    if action in ("check", "review"):
        payload = {
            "order": order, "documents": results, "unverified_actuals": rejected,
            "manual_verification_pending": bool(attestation and not manual_verified),
        }
        if action == "check":
            details = {key: value for key, value in data["details"].items() if key != "bank_account"}
            evidence = {key: value for key, value in data["evidence"].items()
                        if key != "details.bank_account"}
            payload["findings"] = {"details": details, "items": data["items"], "evidence": evidence}
        if action == "review" and ready:
            issued = int(time.time())
            payload["review_token"] = f"{issued}.{digest(json_bytes([issued, binding]))}"
        return payload
    if action == "formal":
        if not ready or not review_token or not re.fullmatch(r"\d+\.[a-f0-9]{64}", review_token):
            raise DocumentError("没有可正式出单的范围，或缺少本次核对编号。")
        issued, key = review_token.split(".")
        issued = int(issued)
        if not 0 <= time.time() - issued < REVIEW_SECONDS or key != digest(json_bytes([issued, binding])):
            raise DocumentError("核对已过期或资料、单据范围有变，请重新核对。")
        # A formal run never commits after a cancelled or unavailable desktop decision.
        summaries = []
        for kind in ready:
            details = results[kind]["adopted"]
            rows = results[kind]["items"]
            quantity_key = "quantity" if kind == "pi" else "shipped_quantity"
            quantity = sum(row[quantity_key] for row in rows)
            summaries.append(
                f"{kind.upper()}：{details['seller']} → {details['buyer']}；"
                f"付款 {details['payment']}；交货 {details['delivery']}；"
                f"数量 {quantity:g} {rows[0]['unit']}；"
                + (f"金额 {results[kind]['amount']:,.2f} {details['currency']}；"
                   if kind != "pl" else "")
                + (f"实际净重 {sum(row['net_kg'] for row in rows):g} kg，"
                   f"实际毛重 {details['gross_kg']:g} kg；" if kind != "pi" else "")
                + (f"箱数 {sum(row['cartons'] for row in rows)}；" if kind == "pl" else "")
            )
        try:
            approved = approve_on_desktop(f"订单：{order}\n" + "\n".join(summaries)
                                          + "\n请核对 WorkBuddy 展示的明细并本人确认。")
        except ApprovalUnavailable as exc:
            raise DocumentError(str(exc)) from exc
        if not approved:
            raise DocumentError("桌面确认未通过，已保留当前成果。")
        if time.time() - issued >= REVIEW_SECONDS:
            raise DocumentError("核对已过期，请重新核对。")
        verify_inputs(store, source_hashes, snapshot, raw, state_hash)
        for kind in selected:
            if kind in artifacts:
                store.check_file(kind, artifacts[kind])

    files = {}
    changed = []
    attempt = None
    for kind in selected:
        existing = artifacts.get(kind)
        status = "formal" if action == "formal" and kind in ready else "draft"
        revision = signature(data, kind, status)
        keep_formal = action == "draft" and existing and existing["status"] == "formal"
        if existing and (
            (existing["signature"] == revision and existing["status"] == status)
            or (keep_formal and kind not in stale)
        ):
            files[kind] = {**existing, "updated": False}
            continue
        if attempt is None:
            attempt = store.start()
        target = attempt / f"{order}_{kind}.xlsx"
        version = (existing or {}).get("version", 0) + 1
        if status == "formal":
            write_formal(target, data, order, kind, version)
        else:
            write_draft(target, data, order, kind, checks[kind], version)
        record = {
            "path": str(target), "sha256": file_digest(target), "signature": revision,
            "status": status, "version": version,
        }
        artifacts[kind] = record
        files[kind] = {**record, "updated": True}
        changed.append(kind)

    receipt = {"action": action, "requested": list(selected), "changed": changed}
    if (attempt is not None or pending or raw != current.get("data")
            or source_hashes != current.get("sources")):
        verify_inputs(store, source_hashes, snapshot, raw, state_hash)
        for kind, record in artifacts.items():
            store.check_file(kind, record)
        if attempt is None:
            attempt = store.start()
        store.commit(attempt, {
            "data": raw, "sources": source_hashes, "artifacts": artifacts, "receipt": receipt,
        })
    for kind, result in results.items():
        result["file"] = files[kind]
    return {
        "order": order, "status": "committed", "receipt": receipt, "documents": results,
        "draft_pending": {
            kind: draft_pending(data, kind) for kind, record in files.items()
            if record["status"] == "draft"
        },
        "unverified_actuals": rejected,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=(
        "check", "review", "draft", "formal", "snapshot", "status", "delivery", "confirm-actuals",
    ))
    parser.add_argument("order")
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--documents", nargs="+", choices=DOCUMENT_NAMES)
    parser.add_argument("--review-token")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--file", type=Path, action="append", default=[], help="本轮交付对应的已提交文件")
    args = parser.parse_args()
    if args.file and args.action != "delivery":
        parser.error("--file 只用于汇总交付。")
    if args.sync and args.action == "delivery":
        parser.error("汇总交付请明确指定本轮需要交付的单据和文件。")
    sys.path.insert(0, str(args.engine))
    try:
        with workspace_lock(args.root):
            result = run(args.root, args.action, args.order, args.documents,
                         args.source, args.snapshot, args.review_token, args.sync,
                         delivery_files=args.file)
        links = delivery_markdown(result, args.action, args.documents, sync=args.sync)
        if links:
            reply = delivery_markdown(
                result, args.action, args.documents, sync=args.sync, include_pending=True,
            )
            result = {"delivery_reply": reply, "delivery_markdown": links, **result}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (DocumentError, OrderStoreError, SetupError) as exc:
        parser.exit(1, str(exc) + "\n")
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        parser.exit(1, "无法读取或保存本单，请核对输入字段、文件和输出目录。\n")


if __name__ == "__main__":
    main()
