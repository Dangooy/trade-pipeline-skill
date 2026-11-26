"""Synthetic acceptance of the WorkBuddy order orchestration."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment

from workbuddy.scripts import documents as doc
from workbuddy.scripts.intake import inspect_workbook

ALL = ("pi", "ci", "pl")


class OrderCase:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.order = "DEMO-6"
        self.source = tmp_path / "fictional_quotation.xlsx"
        self.sources = [self.source]
        self.input = tmp_path / "order-input.json"
        self.output = tmp_path / "output" / self.order
        book = Workbook()
        book.active.title = "Quote"
        book.active.append(["Description", "Spec", "Material", "Finish", "Qty", "Unit", "Price"])
        for index in range(1, 7):
            book.active.append([f"Demo part {index}", f"M{index + 2}", "Steel", "Zinc",
                                1000 * index, "pcs", 10 * index])
        book.save(self.source)
        book.close()
        self.original = self.source.read_bytes()
        extracted = tmp_path / "extracted.json"
        inspect_workbook(self.source, extracted)
        rows = json.loads(extracted.read_text())["Quote"]
        details = {
            "seller": "DEMO EXPORT LTD", "buyer": "DEMO IMPORT LTD",
            "currency": "CNY", "price_unit": "CNY/MPCS",
            "payment": "Payment before shipment", "delivery": "CIF DEMO PORT",
            "port_loading": "DEMO ORIGIN", "port_destination": "DEMO PORT",
            "date": "2026-11-20", "bank_name": "DEMO BANK",
            "bank_account": "TEST ACCOUNT", "swift": "TESTCNSH",
        }
        self.data = {
            "details": details, "items": [],
            "evidence": {f"details.{key}": ["confirmed", "Synthetic order confirmation"]
                         for key in details},
        }
        fields = ("description", "spec", "material", "finish", "quantity", "unit", "unit_price")
        for index in range(1, 7):
            cells = rows[str(index + 1)]
            self.data["items"].append(dict(zip(fields, cells.values(), strict=True)))
            for field, column in zip(fields, cells, strict=True):
                self.data["evidence"][f"items.{index}.{field}"] = [
                    "source", f"Quote!{column}{index + 1}",
                ]

    def actual(self, *, manual=False):
        path = self.root / "fictional_shipment.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Shipment"
        for pos, (key, value) in enumerate({
            "ci_number": "CI-DEMO-6", "gross_kg": 97.5, "packing": "Verified cartons",
        }.items(), 1):
            sheet.append([key, value])
            self.data["details"][key] = value
            self.data["evidence"][f"details.{key}"] = (
                ["confirmed", "Fictional packing record"] if manual
                else ["source", f"{path.name}#Shipment!B{pos}"]
            )
        sheet.append(["description", "shipped_quantity", "invoice_unit_price", "net_kg", "cartons"])
        for index, row in enumerate(self.data["items"], 1):
            actual = {
                "shipped_quantity": row["quantity"], "invoice_unit_price": row["unit_price"],
                "net_kg": index * 4.25, "cartons": index + 2,
            }
            row.update(actual)
            sheet.append([row["description"], *actual.values()])
            for column, key in zip("BCDE", actual, strict=True):
                self.data["evidence"][f"items.{index}.{key}"] = (
                    ["confirmed", f"Synthetic shipment record row {index}"] if manual
                    else ["source", f"{path.name}#Shipment!{column}{index + 4}"]
                )
        if not manual:
            book.save(path)
            if path not in self.sources:
                self.sources.append(path)
        book.close()

    def call(self, action, types=None, *, include_input=True, **kwargs):
        if include_input:
            self.input.write_text(json.dumps(self.data), encoding="utf-8")
        return doc.run(self.root, action, self.order, types,
                       self.sources if include_input else (),
                       self.input if include_input else None, **kwargs)

    def status(self):
        return self.call("status", include_input=False)

    def file(self, kind):
        return Path(self.status()["documents"][kind]["path"])

    def sheet(self, kind):
        book = load_workbook(self.file(kind))
        try:
            return list(book.active.values)
        finally:
            book.close()

    def files(self):
        return sorted(Path(record["path"]).name.rsplit("_", 1)[-1]
                      for record in self.status()["documents"].values())


@pytest.fixture
def order(tmp_path):
    return OrderCase(tmp_path)


def test_a_pi_only_and_preserves_original(order):
    result = order.call("draft", ("pi",))["documents"]
    assert set(result) == {"pi"}
    assert result["pi"]["file"]["status"] == "draft"
    assert order.files() == ["pi.xlsx"]
    assert order.source.read_bytes() == order.original
    assert "INTERNAL DRAFT" in order.sheet("pi")[0][0]


def test_delivery_reports_pending_draft_fields_even_when_formal_check_is_clear(order):
    order.actual()
    del order.data["details"]["price_unit"], order.data["evidence"]["details.price_unit"]
    del order.data["items"][0]["unit_price"], order.data["evidence"]["items.1.unit_price"]
    del order.data["items"][0]["spec"], order.data["evidence"]["items.1.spec"]

    result = order.call("draft", ("pi", "pl"))
    assert result["documents"]["pl"]["missing"] == []
    assert {"卖方地址", "买方地址", "规格"} <= set(result["draft_pending"]["pl"]["fields"])
    assert {"计价单位", "报价单价"} <= set(result["draft_pending"]["pi"]["fields"])
    assert result["draft_pending"]["pi"]["amount_pending"]
    assert not result["draft_pending"]["pl"]["amount_pending"]
    sheet = order.sheet("pl")
    assert any(row[:2] == ("卖方地址", "待确认") for row in sheet)
    assert any(row[:2] == ("Demo part 1", "待确认") for row in sheet)

    message = doc.delivery_markdown(result, "draft", include_pending=True)
    assert message.splitlines()[0].startswith("- [形式发票（PI）]")
    assert message.splitlines()[1].startswith("- [装箱单（PL）]")
    assert "形式发票（PI）的金额待核算" in message
    assert "装箱单（PL）的卖方地址、买方地址" in message
    assert "装箱单（PL）的金额" not in message
    assert "规格" in message
    assert doc.delivery_markdown(
        order.status(), "status", ("pi", "pl"), include_pending=True,
    ) == message
    pi_only = doc.delivery_markdown(order.status(), "status", ("pi",), include_pending=True)
    assert "待核算" in pi_only and "装箱单" not in pi_only


def test_delivery_groups_split_commits_without_relaxing_recovery(order):
    order.actual()
    del order.data["details"]["price_unit"], order.data["evidence"]["details.price_unit"]
    pl = order.call("draft", ("pl",))
    pl_path = Path(pl["documents"]["pl"]["file"]["path"])
    before_pi = doc.delivery_markdown(pl, "draft", include_pending=True)
    assert before_pi.startswith("- [装箱单（PL）]") and "形式发票" not in before_pi
    assert order.call("delivery", ("pi", "pl"), include_input=False,
                      delivery_files=(pl_path, pl_path.with_name("DEMO-6_pi.xlsx")))["status"] == "blocked"

    pi = order.call("draft", ("pi",), include_input=False)
    pi_path = Path(pi["documents"]["pi"]["file"]["path"])
    previous = order.status()
    assert order.call("status", ("pi", "pl"), include_input=False)["status"] == "blocked"
    result = order.call("delivery", ("pi", "pl"), include_input=False,
                        delivery_files=(pl_path, pi_path))
    assert result["status"] == "committed"
    assert set(result["documents"]) == {"pi", "pl"}
    assert all(record["status"] == "draft" for record in result["documents"].values())
    reply = doc.delivery_markdown(result, "delivery", include_pending=True)
    pi_link, pl_link = reply.split("\n\n", 1)[0].splitlines()
    assert pi_link.startswith("- [形式发票（PI）]") and str(pi_path) in pi_link
    assert pl_link.startswith("- [装箱单（PL）]") and str(pl_path) in pl_link
    assert "形式发票（PI）的金额待核算" in reply
    assert "装箱单（PL）的卖方地址、买方地址" in reply
    assert order.status() == previous

    order.data["details"]["price_unit"] = "CNY/MPCS"
    order.data["evidence"]["details.price_unit"] = ["confirmed", "Synthetic selection"]
    order.call("draft", ("pi",))
    stale = order.call("delivery", ("pi", "pl"), include_input=False,
                       delivery_files=(pl_path, pi_path))
    assert stale["status"] == "blocked"
    assert not doc.delivery_markdown(stale, "delivery", include_pending=True)


@pytest.mark.parametrize("count,basis,with_reference_note", [
    (6, "CNY per 1,000 PCS", True),
    (10, "CNY/1,000 PCS", False),
])
def test_explicit_quote_basis_calculates_without_user_confirmation(
    order, count, basis, with_reference_note,
):
    book = Workbook()
    sheet = book.active
    sheet.title = "Quote"
    sheet.append(["Description", "Spec", "Qty", "Unit", basis])
    order.data["evidence"] = {
        key: value for key, value in order.data["evidence"].items() if key.startswith("details.")
    }
    order.data["details"]["price_unit"] = basis
    order.data["evidence"]["details.price_unit"] = ["source", "Quote!E1，按原表核对"]
    order.data["items"] = []
    expected = []
    for i in range(1, count + 1):
        qty, price = 500 * i, 12 * i
        sheet.append([f"Demo part {i}", f"M{i}", qty, "pcs", price])
        if with_reference_note:
            sheet[f"E{i + 1}"].comment = Comment(
                "Equivalent reference: 8 CNY/kg", "Fictional quote",
            )
        order.data["items"].append(dict(
            description=f"Demo part {i}", spec=f"M{i}", quantity=qty, unit="pcs", unit_price=price,
        ))
        expected.append(qty * price / 1000)
        for column, field in zip("ABCDE", order.data["items"][-1], strict=True):
            order.data["evidence"][f"items.{i}.{field}"] = [
                "source", f"Quote!{column}{i + 1}",
            ]
    book.save(order.source)
    book.close()
    original = order.source.read_bytes()
    result = order.call("draft", ALL)["documents"]
    pi = order.sheet("pi")
    header = next(row for row in pi if "报价单价" in row)
    products = [row for row in pi if str(row[0]).startswith("Demo part")]
    assert [row[header.index("金额")] for row in products] == expected
    assert result["pi"]["amount"] == sum(expected)
    assert result["ci"]["amount"] is None
    assert order.source.read_bytes() == original
    saved = order.call("snapshot", include_input=False)
    assert saved["evidence"]["details.price_unit"] == ["source", "Quote!E1，按原表核对"]


def test_b_six_rows_share_one_parse_and_dont_invent_actuals(order, monkeypatch):
    # The fixture extracted the source once. Subsequent operations use the saved snapshot.
    def unexpected_parse(*args, **kwargs):
        pytest.fail("A document writer attempted another input workbook parse")
    monkeypatch.setattr("workbuddy.scripts.intake.load_workbook", unexpected_parse)
    first = order.call("draft", ALL)["documents"]
    second = order.call("draft", ALL, include_input=False)["documents"]
    assert order.files() == ["ci.xlsx", "pi.xlsx", "pl.xlsx"]
    assert all(not item["file"]["updated"] for item in second.values())
    assert all(item["file"]["version"] == 1 for item in first.values())
    for kind in ALL:
        sheet = order.sheet(kind)
        products = [row for row in sheet if isinstance(row[0], str) and row[0].startswith("Demo part")]
        assert [row[:6] for row in products] == [
            (f"Demo part {i}", f"M{i + 2}", "Steel", "Zinc", i * 1000, "pcs")
            for i in range(1, 7)
        ]
        if kind != "pi":
            assert all(row[6] == "待确认" for row in products)
            assert any(row[4] == "报价数量（仅参考）" for row in sheet)
    assert first["pi"]["amount"] == 910
    assert first["ci"]["amount"] is None


def test_c_ci_pl_can_be_issued_without_a_pi(order, monkeypatch):
    order.actual()
    messages = []
    monkeypatch.setattr(doc, "approve_on_desktop", lambda text: messages.append(text) or True)
    review = order.call("review", ("ci", "pl"))
    assert all(item["can_issue"] for item in review["documents"].values())
    result = order.call("formal", ("ci", "pl"), review_token=review["review_token"])["documents"]
    assert set(result) == {"ci", "pl"} and order.files() == ["ci.xlsx", "pl.xlsx"]
    assert len(messages) == 1 and "CIF DEMO PORT" in messages[0]
    assert "金额 910.00 CNY" in messages[0]
    ci = order.sheet("ci")
    pl = order.sheet("pl")
    assert any("CNY / CIF DEMO PORT" in row for row in ci)
    assert any("Order No.:DEMO-6" in row for row in ci)
    assert any(row[-2:] == ("Order No.:", "DEMO-6") for row in pl)
    assert any("SAY: CNY NINE HUNDRED TEN ONLY." in row for row in ci)
    total = next(row for row in pl if "TOTAL:" in row)
    assert total[2:7] == (33, None, 21000, 89.25, 97.5)
    assert not any("EURO-PALLET" in str(cell) for row in pl for cell in row)


def test_b_complete_order_issues_three_from_the_same_numbers(order, monkeypatch):
    order.actual()
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: True)
    review = order.call("review", ALL)
    issued = order.call("formal", ALL, review_token=review["review_token"])["documents"]
    assert issued["pi"]["amount"] == issued["ci"]["amount"] == 910
    assert all(item["file"]["status"] == "formal" for item in issued.values())
    pi_rows = [row[11] for row in order.sheet("pi") if str(row[0]).startswith("Demo part")]
    ci_rows = [row[13] for row in order.sheet("ci") if str(row[2]).startswith("Demo part")]
    pl_rows = [row[4] for row in order.sheet("pl") if str(row[1]).startswith("Demo part")]
    assert pi_rows == ci_rows == pl_rows == list(range(1000, 7000, 1000))
    assert order.files() == ["ci.xlsx", "pi.xlsx", "pl.xlsx"]
    # A quote-only edit must not turn actual shipment data into revised estimates.
    order.data["items"][0]["quantity"] = 20000
    order.data["evidence"]["items.1.quantity"] = ["confirmed", "Updated quote only"]
    revision = order.call("draft", ("pi",), sync=True)["documents"]
    assert set(revision) == {"pi"}
    assert revision["pi"]["file"]["version"] == 2
    assert order.files() == ["ci.xlsx", "pi.xlsx", "pl.xlsx"]


def test_d_shared_edits_update_current_versions_and_invalidate_review(order):
    original = order.call("draft", ALL)["documents"]
    review = order.call("review", ALL, include_input=False)
    order.data["items"][0]["quantity"] = 20000
    order.data["evidence"]["items.1.quantity"] = ["confirmed", "Fictional revision"]
    with pytest.raises(doc.DocumentError, match="重新核对"):
        order.call("formal", ALL, review_token=review["review_token"])
    updated = order.call("draft", ("pi",), sync=True)["documents"]
    assert len(updated) == 3
    assert updated["pi"]["amount"] == 1100
    for kind in ALL:
        assert updated[kind]["file"]["version"] == 2
        assert updated[kind]["file"]["path"] != original[kind]["file"]["path"]
        assert doc.file_digest(Path(original[kind]["file"]["path"])) == original[kind]["file"]["sha256"]
        assert any(row[0] == "Demo part 1" and row[4] == 20000 for row in order.sheet(kind))
    order.data["details"]["lead_time"] = "Four weeks"
    order.data["evidence"]["details.lead_time"] = ["confirmed", "PI delivery timetable"]
    change = order.call("draft", ("pi",), sync=True)["documents"]
    assert set(change) == {"pi"}
    assert order.files() == ["ci.xlsx", "pi.xlsx", "pl.xlsx"]


def test_e_missing_terms_makes_drafts_and_does_not_confirm(order, monkeypatch):
    for key in ("payment", "delivery"):
        order.data["details"].pop(key)
        order.data["evidence"].pop(f"details.{key}")
    order.data["items"][0].pop("unit_price")
    order.data["evidence"].pop("items.1.unit_price")
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: pytest.fail("Approval called"))
    review = order.call("review", ALL)
    assert "review_token" not in review
    result = order.call("draft", ALL)["documents"]
    assert all(not item["can_issue"] and item["file"]["status"] == "draft"
               for item in result.values())
    assert {"付款条件", "贸易条件及地点"} <= set(result["pi"]["missing"])
    assert any("待核算" in row for row in order.sheet("pi"))
    assert any(row[:2] == ("实际总毛重 (kg)", "待确认") for row in order.sheet("pl"))
    assert all(row[6:9] == ("待确认", "待确认", "待确认")
               for row in order.sheet("pl") if str(row[0]).startswith("Demo part"))


def test_f_check_is_read_only(order):
    result = order.call("check")
    assert result["findings"]["evidence"]["items.1.quantity"] == ["source", "Quote!E2"]
    assert result["documents"]["pi"]["amount"] == 910
    assert not order.output.exists()
    assert not (order.root / ".workbuddy-orders").exists()
    assert order.source.read_bytes() == order.original


def test_g_mixed_formal_can_cancel_then_promote_one_current_file(order, monkeypatch):
    order.call("draft", ALL)
    review = order.call("review", ALL, include_input=False)
    versions = {name: doc.file_digest(order.file(name)) for name in ALL}
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: False)
    with pytest.raises(doc.DocumentError, match="未通过"):
        order.call("formal", ALL, include_input=False, review_token=review["review_token"])
    assert all(doc.file_digest(order.file(name)) == old
               for name, old in versions.items())
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: True)
    result = order.call("formal", ALL, include_input=False, review_token=review["review_token"])[
        "documents"
    ]
    assert result["pi"]["file"]["status"] == "formal"
    assert result["pi"]["file"]["version"] == 2
    assert result["ci"]["file"]["status"] == result["pl"]["file"]["status"] == "draft"
    assert result["ci"]["file"]["version"] == result["pl"]["file"]["version"] == 1
    assert len(order.files()) == 3
    assert any(isinstance(cell, str) and "/1000*" in cell for row in order.sheet("pi") for cell in row)
    assert order.source.read_bytes() == order.original


def test_g_tampered_outputs_and_order_review_expiry(order, monkeypatch):
    review = order.call("review", ("pi",))
    issued = int(review["review_token"].split(".")[0])
    monkeypatch.setattr(doc.time, "time", lambda: issued + doc.REVIEW_SECONDS)
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: pytest.fail("Approval called"))
    with pytest.raises(doc.DocumentError, match="已过期"):
        order.call("formal", ("pi",), review_token=review["review_token"])
    order.output.mkdir(parents=True)
    customer_file = order.output / f"{order.order}_pi.xlsx"
    customer_file.write_bytes(order.original)
    order.call("draft", ("pi",))
    assert order.file("pi") != customer_file
    assert customer_file.read_bytes() == order.original


def test_interruption_after_first_file_keeps_complete_current_and_allows_retry(order, monkeypatch):
    order.call("draft", ALL)
    baseline = order.status()
    old_files = {kind: Path(record["path"]).read_bytes()
                 for kind, record in baseline["documents"].items()}
    write = doc.write_draft

    def stop_after_pi(path, data, order_no, kind, missing, version):
        if kind == "pl":
            raise PermissionError("simulated interruption")
        write(path, data, order_no, kind, missing, version)

    order.data["items"][0]["quantity"] = 20000
    with monkeypatch.context() as injected:
        injected.setattr(doc, "write_draft", stop_after_pi)
        with pytest.raises(PermissionError, match="interruption"):
            order.call("draft", ALL)
    pending = order.status()
    assert pending["documents"] == baseline["documents"]
    assert pending["pending_attempts"] == 1
    completed = order.call("draft", ALL)
    assert all(result["file"]["version"] == 2 for result in completed["documents"].values())
    assert order.status()["receipt"]["changed"] == list(doc.DOCUMENT_NAMES)
    assert order.status()["pending_attempts"] == 0
    assert all(Path(baseline["documents"][kind]["path"]).read_bytes() == before
               for kind, before in old_files.items())


def test_abrupt_interruption_keeps_uncommitted_pi_out_of_receipt(order):
    order.call("draft", ("ci", "pl"))
    before = order.status()
    child = """
import os
import sys
from pathlib import Path
from workbuddy.scripts import documents as doc

write = doc.write_draft
def exit_after_pi(path, data, order, kind, missing, version):
    write(path, data, order, kind, missing, version)
    if kind == "pi":
        os._exit(91)
doc.write_draft = exit_after_pi
doc.run(Path(sys.argv[1]), 'draft', sys.argv[2], ('pi', 'ci', 'pl'))
"""
    result = subprocess.run([sys.executable, "-B", "-c", child, str(order.root), order.order])
    assert result.returncode == 91
    current = order.status()
    assert current["documents"] == before["documents"]
    assert current["pending_attempts"] == 1
    recovered = order.call("draft", ALL, include_input=False)
    assert recovered["receipt"]["changed"] == ["pi"]
    assert set(order.status()["documents"]) == set(ALL)
    assert order.source.read_bytes() == order.original


def test_committed_receipt_survives_lost_formal_response_and_blocks_stale_retry(order, monkeypatch):
    order.actual()
    calls = []
    monkeypatch.setattr(doc, "approve_on_desktop", lambda text: calls.append(text) or True)
    review = order.call("review", ("ci", "pl"))
    commit = doc.OrderStore.commit

    def lose_response(self, attempt, state):
        commit(self, attempt, state)
        raise InterruptedError("lost command response after commit")

    with monkeypatch.context() as injected:
        injected.setattr(doc.OrderStore, "commit", lose_response)
        with pytest.raises(InterruptedError):
            order.call("formal", ("ci", "pl"), review_token=review["review_token"])
    outcome = order.status()
    assert outcome["status"] == "committed"
    assert outcome["receipt"] == {"action": "formal", "requested": ["pl", "ci"], "changed": ["pl", "ci"]}
    assert all(x["status"] == "formal" for x in outcome["documents"].values())
    with pytest.raises(doc.DocumentError, match="重新核对"):
        order.call("formal", ("ci", "pl"), review_token=review["review_token"])
    assert len(calls) == 1
    assert order.status() == outcome


def test_document_generation_needs_no_unlink_rename_or_temp_worksheet(order, monkeypatch):
    order.actual()
    monkeypatch.setattr(doc, "approve_on_desktop", lambda _: True)
    order.call("draft", ALL)
    review = order.call("review", ALL)

    def forbidden(*args, **kwargs):
        pytest.fail("WorkBuddy document path attempted destructive scratch cleanup")

    with monkeypatch.context() as injected:
        for operation in ("remove", "unlink", "rename", "replace", "rmdir", "link"):
            injected.setattr(os, operation, forbidden)
        result = order.call("formal", ALL, review_token=review["review_token"])
        assert result["status"] == "committed"
        assert all(record["status"] == "formal" for record in order.status()["documents"].values())
    assert set(order.status()["documents"]) == set(ALL)


@pytest.mark.parametrize("claim", [
    ["source", "Quote!E2"], ["source", "Shipment!B7"], ["confirmed", "用户已核对"],
])
def test_quote_only_cannot_grant_formal_ci_or_pl(order, claim, monkeypatch):
    order.actual(manual=True)
    for key in order.data["evidence"]:
        if key.startswith("items.") and key.rsplit(".", 1)[-1] in (
            "shipped_quantity", "net_kg", "invoice_unit_price", "cartons"
        ):
            order.data["evidence"][key] = claim
    monkeypatch.setattr(doc, "approve_on_desktop", lambda *_a, **_k: pytest.fail("unexpected pop-up"))
    review = order.call("review", ("ci", "pl"))
    assert "review_token" not in review
    assert not any(item["can_issue"] for item in review["documents"].values())
    assert "items.1.shipped_quantity" in review["unverified_actuals"]
    draft = order.call("draft", ("ci", "pl"))
    assert draft["documents"]["ci"]["amount"] is None
    assert any(row[:2] == ("实际总毛重 (kg)", "待确认") for row in order.sheet("pl"))


@pytest.mark.parametrize("wrong", ["column", "row", "value", "unit"])
def test_actual_document_reference_has_to_match_field_product_and_value(order, wrong):
    order.actual()
    key = "items.1.shipped_quantity"
    if wrong == "column":
        order.data["evidence"][key] = ["source", "Shipment!C5"]
    elif wrong == "row":
        order.data["items"][0]["shipped_quantity"] = 2000
        order.data["evidence"][key] = ["source", "Shipment!B6"]
    elif wrong == "value":
        order.data["items"][0]["shipped_quantity"] = 9999
    else:
        # Where a shipment unit column is present, it is part of the actual quantity evidence.
        workbook = load_workbook(order.sources[-1])
        workbook.active["F4"] = "unit"
        workbook.active["F5"] = "kg"
        workbook.save(order.sources[-1])
        workbook.close()
    result = order.call("review", ("ci", "pl"))
    assert key in result["unverified_actuals"]
    assert "review_token" not in result


def test_manual_verification_is_real_separate_and_survives_quote_only_revision(order, monkeypatch):
    order.actual(manual=True)
    review = order.call("review", ("ci", "pl"))
    assert review["manual_verification_pending"]
    assert "review_token" not in review
    seen = []
    def ask(text, *, verifying_actuals=False):
        seen.append((verifying_actuals, text))
        return len(seen) > 1
    monkeypatch.setattr(doc, "approve_on_desktop", ask)
    with pytest.raises(doc.DocumentError, match="未确认"):
        order.call("confirm-actuals")
    assert order.status()["status"] == "not_committed"
    before = order.call("confirm-actuals")
    assert before["status"] == "actuals_verified"
    assert order.call("confirm-actuals") == before and len(seen) == 2
    assert seen[1][0] and "实际出货数量：1000" in seen[1][1]
    review = order.call("review", ("ci", "pl"))
    assert "review_token" in review and not review["manual_verification_pending"]
    order.data["items"][0]["quantity"] = 20000
    with pytest.raises(doc.DocumentError, match="重新核对"):
        order.call("formal", ("ci", "pl"), review_token=review["review_token"])
    second = order.call("review", ("ci", "pl"))
    assert second["documents"]["ci"]["items"][0]["shipped_quantity"] == 1000
    order.data["items"][0]["net_kg"] = 99
    assert "review_token" not in order.call("review", ("ci", "pl"))
