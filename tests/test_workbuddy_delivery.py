"""Receipt-derived file links for WorkBuddy's chat renderer."""
from pathlib import Path

import pytest

from workbuddy.scripts.delivery import delivery_markdown


def committed_receipt(root, *, recovery=False):
    result = {"order": "DEMO-6", "status": "committed"}
    result["receipt"] = {"action": "draft", "requested": ["pi", "pl", "ci"], "changed": ["pi", "pl", "ci"]}
    result["documents"] = {}
    for kind in ("pi", "pl", "ci"):
        record = {
            "path": str(root / f"DEMO-6_{kind}.xlsx"),
            "status": "draft" if kind != "ci" else "formal",
            "version": 1 if kind != "ci" else 3,
        }
        result["documents"][kind] = record if recovery else {"file": record}
    return result


def test_first_delivery_has_one_clickable_line_per_committed_excel():
    result = committed_receipt(Path("/private/tmp/wb-test"))
    assert delivery_markdown(result, "draft").splitlines() == [
        "- [形式发票（PI）](/private/tmp/wb-test/DEMO-6_pi.xlsx) · 内部工作稿",
        "- [商业发票（CI）](/private/tmp/wb-test/DEMO-6_ci.xlsx) · 正式单据 · 本次更新",
        "- [装箱单（PL）](/private/tmp/wb-test/DEMO-6_pl.xlsx) · 内部工作稿",
    ]
    assert "delivery_markdown" not in result


def test_unrequested_unchanged_and_bad_paths_are_not_listed():
    result = committed_receipt(Path("/private/tmp/wb-test"))
    result["receipt"]["requested"] = ["pi", "pl"]
    result["receipt"]["changed"] = ["pi", "ci"]
    assert "DEMO-6_pi.xlsx" in delivery_markdown(result, "draft", sync=True)
    assert len(delivery_markdown(result, "draft", sync=True).splitlines()) == 1
    result["documents"]["pi"]["file"]["path"] = "DEMO-6_pi.xlsx"
    result["documents"]["pl"]["file"]["path"] = "/private/tmp/another-order_pl.xlsx"
    assert not delivery_markdown(result, "draft")


def test_recovery_preserves_explicit_scope_and_link_syntax_for_special_paths():
    result = committed_receipt(Path("/private/tmp/虚构 订单 (第1批)#1"), recovery=True)
    assert delivery_markdown(result, "status", ("ci",), sync=True) == (
        "- [商业发票（CI）](</private/tmp/虚构 订单 (第1批)%231/DEMO-6_ci.xlsx>)"
        " · 正式单据 · 本次更新"
    )


@pytest.mark.parametrize("state", ["pending", "blocked", "not_committed"])
def test_incomplete_or_stale_receipts_offer_no_workbook_links(state):
    result = committed_receipt(Path("/private/tmp/wb-test"), recovery=True)
    result["status"] = state
    assert not delivery_markdown(result, "status")


@pytest.mark.parametrize("action", ["check", "review", "snapshot", "confirm-actuals"])
def test_read_only_or_approval_exchange_does_not_deliver_files(action):
    assert not delivery_markdown(committed_receipt(Path("/private/tmp/wb-test")), action)
