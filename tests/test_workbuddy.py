"""WorkBuddy wrapper regressions that do not require network access."""
import hashlib
import json

import pytest
import yaml
from openpyxl import Workbook, load_workbook

from workbuddy.scripts.business import SetupError, patch_config
from workbuddy.scripts.intake import inspect_workbook, write_draft


def test_patch_keeps_formats_and_nested_fields(tmp_path):
    path = tmp_path / "config.yaml"
    original = b"""# Original
sellers:
  real:
    name_en: Prior Company
    bank:
      account_no: '123'
format_defaults:
  standard: {seller_id: real, currency: CNY}
  standard_usd: {seller_id: real, currency: USD}
  washers_mar: {seller_id: real, currency: USD}
pallet_presets:
  euro: {width_mm: 800}
product_catalog:
  item: {weight_kg: 1.5}
"""
    path.write_bytes(original)
    change = tmp_path / "changes.json"
    change.write_text('{"sellers":{"real":{"name_en":"Updated Name"}}}', encoding="utf-8")
    revision = hashlib.sha256(original).hexdigest()
    patch_config(path, change, revision)
    expected = yaml.safe_load(original)
    expected["sellers"]["real"]["name_en"] = "Updated Name"
    assert yaml.safe_load(path.read_bytes()) == expected
    assert next(tmp_path.glob("config-*.yaml.bak")).read_bytes() == original

    already_updated = path.read_bytes()
    with pytest.raises(SetupError, match="配置已改动"):
        patch_config(path, change, revision)
    assert path.read_bytes() == already_updated


def test_intake_preserves_sources_and_draft_leaves_missing_values(tmp_path):
    source = tmp_path / "inquiry.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Запрос"
    sheet.append(["Материал", "Покрытие", "Количество", "Расчёт"])
    sheet.append(["Сталь", "Цинк", 100, "=C2*2"])
    workbook.save(source)
    workbook.close()

    original = source.read_bytes()
    extracted = tmp_path / "source.json"
    inspect_workbook(source, extracted)
    row = json.loads(extracted.read_text(encoding="utf-8"))["Запрос"]["2"]
    assert row == {"A": "Сталь", "B": "Цинк", "C": 100, "D": "待确认（原公式无缓存结果）"}
    assert source.read_bytes() == original

    data = tmp_path / "draft.json"
    data.write_text(json.dumps({"items": [{
        "description": "=Untrusted text", "material": row["A"], "finish": row["B"],
        "quantity": row["C"], "source": "Запрос!2",
    }]}), encoding="utf-8")
    draft = tmp_path / "draft.xlsx"
    write_draft(data, draft)
    saved = load_workbook(draft)
    sheet = saved.active
    assert sheet["A11"].value == "=Untrusted text"
    assert sheet["A11"].data_type == "s"
    assert sheet["C11"].value == "Сталь"
    assert sheet["E11"].value == 100
    assert sheet["G11"].value == "待确认"
    assert sheet["I11"].value == "Запрос!2"
    assert sheet["B4"].value == "待确认"
    saved.close()
    with pytest.raises(FileExistsError):
        write_draft(data, draft)


@pytest.fixture
def formal_order(tmp_path):
    from copy import deepcopy

    from tests.conftest import SAMPLE_CONFIG, make_model
    from trade_pipeline.understanding.assembler import resolve_entities
    from trade_pipeline.writers.quote_writer import QuoteWriter

    config = deepcopy(SAMPLE_CONFIG)
    config_path = tmp_path / "business.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    model = make_model()
    model.derived.port_of_destination = "CHICAGO, USA"
    model_path = tmp_path / "model.json"
    model.to_json(model_path)
    quotation = tmp_path / "quotation.xlsx"
    priced_model = make_model(with_prices=True)
    QuoteWriter(resolve_entities(priced_model, config), config).write(quotation)
    return config_path, quotation, model_path


def _formal_files(model):
    return sorted(path.name for path in model.parent.glob("TEST01_*.xlsx"))


def _approval(order, capsys, **options):
    from workbuddy.scripts.formal import review_and_write

    review_and_write(*order, review=True, **options)
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("payment", None, "付款条款"),
    ("delivery", None, "交货条款"),
    ("payment", "   ", "付款条款"),
    ("delivery", "FOB, port TBD", "交货条款"),
    ("payment", "Payment: N/A", "付款条款"),
])
def test_formal_requires_each_term(formal_order, field, value, message):
    from workbuddy.scripts.formal import FormalError, review_and_write

    config_path, _, model_path = formal_order
    config = yaml.safe_load(config_path.read_bytes())
    terms = config["terms_templates"]["default_usd"]
    if value is None:
        terms.pop(field)
    else:
        terms[field] = value
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = model_path.read_bytes()
    from contextlib import redirect_stdout
    from io import StringIO

    preview = StringIO()
    with redirect_stdout(preview):
        review_and_write(*formal_order, review=True)
    data = json.loads(preview.getvalue())
    assert data["状态"] == "待确认"
    assert message in data["缺少条款"]
    assert data["核对编号"] is None
    retained = "payment" if field == "delivery" else "delivery"
    assert data["本单条款"][retained] == terms[retained]
    with pytest.raises(FormalError, match=message):
        review_and_write(*formal_order, review_token="确认")
    assert model_path.read_bytes() == original
    assert _formal_files(model_path) == []


def test_formal_requires_explicit_confirmation(formal_order, capsys):
    from workbuddy.scripts.formal import FormalError, review_and_write

    model = formal_order[-1]
    original = model.read_bytes()
    approval = _approval(formal_order, capsys)
    assert approval["订单号"] == "TEST01"
    assert approval["本单条款"]["payment"].startswith("30% T/T")
    assert approval["本单条款"]["delivery"].startswith("FOB QINGDAO")
    with pytest.raises(FormalError, match="先查看本单核对结果"):
        review_and_write(*formal_order)
    with pytest.raises(FormalError, match="不匹配"):
        review_and_write(*formal_order, review_token="继续")
    assert model.read_bytes() == original
    assert _formal_files(model) == []


@pytest.mark.parametrize("changed", ["order", "terms", "quotation"])
def test_formal_confirmation_expires_when_inputs_change(formal_order, capsys, changed):
    from workbuddy.scripts.formal import FormalError, review_and_write

    config, quote, model = formal_order
    approval = _approval(formal_order, capsys)["核对编号"]
    if changed == "order":
        order = json.loads(model.read_bytes())
        order["order"]["order_no"] = "TEST02"
        model.write_text(json.dumps(order), encoding="utf-8")
    elif changed == "terms":
        data = yaml.safe_load(config.read_bytes())
        data["terms_templates"]["default_usd"]["payment"] = "100% T/T before shipment"
        config.write_text(yaml.safe_dump(data), encoding="utf-8")
    else:
        workbook = load_workbook(quote)
        price_cell = next(
            row[5] for row in workbook.active.iter_rows() if row[8].value == "abc123def456"
        )
        price_cell.value = 31.5
        workbook.save(quote)
        workbook.close()
    before = model.read_bytes()
    with pytest.raises(FormalError, match="不匹配"):
        review_and_write(*formal_order, review_token=approval)
    assert model.read_bytes() == before
    assert sorted(path.name for path in model.parent.glob("*.xlsx")) == ["quotation.xlsx"]


def test_formal_confirmed_order_writes_pi_ci_and_pl(formal_order, capsys, monkeypatch):
    from workbuddy.scripts.formal import review_and_write

    documents = ("pi", "ci", "pl")
    approval = _approval(formal_order, capsys, documents=documents)
    model = formal_order[-1]
    original = model.read_bytes()
    config_bytes = formal_order[0].read_bytes()
    quotation_bytes = formal_order[1].read_bytes()
    decisions = []
    monkeypatch.setattr(
        "workbuddy.scripts.formal.approve_on_desktop", lambda message: not decisions.append(message),
    )
    review_and_write(*formal_order, review_token=approval["核对编号"], documents=documents)
    assert len(decisions) == 1
    assert all(approval["本单条款"][field] in decisions[0] for field in ("payment", "delivery"))
    assert next((model.parent / ".workbuddy-backups").glob("*.bak")).read_bytes() == original
    assert formal_order[0].read_bytes() == config_bytes
    assert formal_order[1].read_bytes() == quotation_bytes
    assert _formal_files(model) == ["TEST01_ci.xlsx", "TEST01_pi.xlsx", "TEST01_pl.xlsx"]
    assert json.loads(model.read_bytes())["items"][0]["unit_price"] == 28.5
    workbook = load_workbook(model.parent / "TEST01_pi.xlsx")
    values = {cell.value for row in workbook.active for cell in row}
    assert set(approval["本单条款"].values()) & values >= {
        approval["本单条款"]["payment"], approval["本单条款"]["delivery"],
    }
    workbook.close()


def test_matching_token_cannot_replace_desktop_confirmation(formal_order, capsys, monkeypatch):
    from workbuddy.scripts.formal import FormalError, review_and_write

    model = formal_order[-1]
    original = model.read_bytes()
    token = _approval(formal_order, capsys)["核对编号"]
    seen = []
    monkeypatch.setattr(
        "workbuddy.scripts.formal.approve_on_desktop", lambda message: seen.append(message),
    )
    with pytest.raises(FormalError, match="桌面确认未通过"):
        review_and_write(*formal_order, review_token=token)
    assert len(seen) == 1
    assert model.read_bytes() == original
    assert _formal_files(model) == []
    assert not (model.parent / ".workbuddy-backups").exists()


def test_file_changes_during_desktop_confirmation_require_new_review(formal_order, capsys,
                                                              monkeypatch):
    from workbuddy.scripts.formal import FormalError, review_and_write

    model = formal_order[-1]
    token = _approval(formal_order, capsys)["核对编号"]
    new_model = json.loads(model.read_bytes())
    new_model["order"]["date"] = "20 November 2026"

    def change_order(_):
        model.write_text(json.dumps(new_model), encoding="utf-8")
        return True

    monkeypatch.setattr("workbuddy.scripts.formal.approve_on_desktop", change_order)
    with pytest.raises(FormalError, match="资料已改动"):
        review_and_write(*formal_order, review_token=token)
    assert json.loads(model.read_bytes()) == new_model
    assert _formal_files(model) == []


def test_requested_pi_only_and_existing_file_is_reused(formal_order, capsys, monkeypatch):
    from workbuddy.scripts.formal import FormalError, review_and_write

    model = formal_order[-1]
    data = json.loads(model.read_bytes())
    data["derived"]["port_of_destination"] = None
    model.write_text(json.dumps(data), encoding="utf-8")

    token = _approval(formal_order, capsys)["核对编号"]
    assert _formal_files(model) == []
    decisions = []
    monkeypatch.setattr(
        "workbuddy.scripts.formal.approve_on_desktop", lambda message: not decisions.append(message),
    )
    with pytest.raises(FormalError, match="输出范围不匹配"):
        review_and_write(*formal_order, review_token=token, documents=("pi", "ci"))
    review_and_write(*formal_order, review_token=token)
    assert _formal_files(model) == ["TEST01_pi.xlsx"]
    assert len(decisions) == 1
    pi = model.parent / "TEST01_pi.xlsx"
    before = pi.read_bytes()
    model_before = model.read_bytes()

    capsys.readouterr()
    retry = _approval(formal_order, capsys)["核对编号"]
    with pytest.raises(FormalError, match="已有同名单据"):
        review_and_write(*formal_order, review_token=retry)
    assert pi.read_bytes() == before
    assert model.read_bytes() == model_before
    assert len(decisions) == 1


def test_publish_collision_rolls_back_prior_new_file(tmp_path):
    from workbuddy.scripts.formal import FormalError, publish_files

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    stage = {kind: scratch / f"{kind}.xlsx" for kind in ("pi", "ci")}
    for p in stage.values():
        p.write_bytes(b"new")
    pi = tmp_path / "pi.xlsx"
    ci = tmp_path / "ci.xlsx"
    ci.write_bytes(b"existing")
    with pytest.raises(FormalError, match="无法安全保存"):
        publish_files(stage, {"pi": pi, "ci": ci}, lambda: pytest.fail("model commit ran"))
    assert not pi.exists()
    assert ci.read_bytes() == b"existing"


def test_desktop_approval_default_is_cancel(monkeypatch):
    from subprocess import CompletedProcess
    from workbuddy.scripts import approval

    monkeypatch.setattr(approval.sys, "platform", "darwin")
    invoked = []

    def run(command, **options):
        invoked.append(command)
        return CompletedProcess(command, 0, "cancelled", "")

    monkeypatch.setattr(approval.subprocess, "run", run)
    assert not approval.approve_on_desktop("TEST01")
    assert invoked[0][0] == "/usr/bin/osascript"
    script = invoked[0][4]
    assert script.index("addButtonWithTitle('取消')") < script.index("addButtonWithTitle('确认出单')")
    assert invoked[0][-1] == "TEST01"


def test_default_workspace_locator_is_read_only(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    import sys

    from workbuddy.scripts import business

    simulated_user = tmp_path / "desktop-user"
    simulated_user.mkdir()
    monkeypatch.setattr(Path, "home", lambda: simulated_user)
    monkeypatch.setattr(sys, "argv", ["business.py", "default", "locate"])
    with pytest.raises(SetupError, match="还没有可复用"):
        business.main()
    assert list(simulated_user.iterdir()) == []
    config = simulated_user / "Documents" / "外贸单证管线" / "engine/trade_pipeline/config/config.yaml"
    config.parent.mkdir(parents=True)
    original = b"sellers: {}\n"
    config.write_bytes(original)
    assert business.main() == 0
    assert capsys.readouterr().out.strip() == str(config)
    assert config.read_bytes() == original
    assert list(config.parents[3].iterdir()) == [config.parents[2]]


def test_windows_desktop_confirmation_uses_default_no(monkeypatch):
    import base64
    from subprocess import CompletedProcess

    from workbuddy.scripts import approval

    monkeypatch.setattr(approval.sys, "platform", "win32")
    invoked = {}

    def run(command, **options):
        invoked.update(command=command, **options)
        return CompletedProcess(command, 0, "approved", "")

    monkeypatch.setattr(approval.subprocess, "run", run)
    assert approval.approve_on_desktop("TEST01")
    assert invoked["command"][0].endswith("powershell.exe")
    script = base64.b64decode(invoked["command"][-1]).decode("utf-16-le")
    assert "MessageBoxDefaultButton]::Button2" in script
    assert "DialogResult]::Yes" in script
    assert invoked["env"]["WORKBUDDY_ORDER_APPROVAL_TEXT"] == "TEST01"
