"""Tests for the pre-generation validation engine (validation/ MVP).

覆盖验收要求：
  - 正常订单无 error
  - 缺公司身份 / 单价 / 数量报 error
  - 缺重量按计价方式分级：吨价 error，其他 warning（与 PL Gateway 业务逻辑一致）
  - 信用证订单只给 info 提醒人工审单，不自动判断条款
  - reporter 输出中文 Markdown / 纯文本报告
"""
from tests.conftest import make_model, make_resolved_model
from trade_pipeline.validation.cross_doc import check_ci_pl_gross_weight
from trade_pipeline.validation.engine import validate_order
from trade_pipeline.validation.models import Severity
from trade_pipeline.validation.reporters import to_markdown, to_text


def rule_ids(results) -> set[str]:
    return {r.rule_id for r in results}


# ── 正常订单 ─────────────────────────────────────────────────────


def test_normal_order_has_no_errors():
    model = make_model(with_prices=True, with_weights=True)
    model.derived.port_of_destination = "CHICAGO, USA"
    report = validate_order(model)
    assert not report.has_errors
    assert report.order_no == "TEST01"


def test_normal_order_still_gets_certificate_info():
    # R010 是常驻 info：模型当前没有证书需求字段，每单都提醒人工确认
    model = make_model(with_prices=True, with_weights=True)
    report = validate_order(model)
    assert "R010" in rule_ids(report.infos)


# ── 身份与订单头 ─────────────────────────────────────────────────


def test_missing_seller_reports_error():
    model = make_model(with_prices=True)
    model.refs.seller_id = ""
    report = validate_order(model)
    assert "R001" in rule_ids(report.errors)


def test_missing_buyer_reports_error():
    model = make_model(with_prices=True)
    model.refs.buyer_id = ""
    report = validate_order(model)
    assert "R002" in rule_ids(report.errors)


def test_missing_terms_reports_error():
    model = make_model(with_prices=True)
    model.refs.terms_id = ""
    report = validate_order(model)
    assert "R003" in rule_ids(report.errors)


# ── R011–R013：出单前的最后一道门禁（不能带缺失的买方/条款/收款信息签发正式单据）──


def test_unresolved_model_does_not_require_resolved_entities():
    """未走 resolve_entities 的模型不应被 R011–R013 误拦。

    这三条规则看的是 `model.resolved`；未解析时它为 None，规则必须直接放行，
    否则报价单阶段（尚未解析实体）会被正式单据的门禁卡住。
    """
    model = make_model(with_prices=True, with_weights=True)
    model.derived.port_of_destination = "CHICAGO, USA"
    report = validate_order(model)
    assert {"R011", "R012", "R013"}.isdisjoint(rule_ids(report.errors))


def test_resolved_buyer_missing_name_reports_error():
    """R011：正式单据不能带空买方抬头。"""
    model = make_resolved_model(with_prices=True)
    model.resolved.buyer = {}
    report = validate_order(model)
    assert "R011" in rule_ids(report.errors)


def test_resolved_terms_missing_reports_error():
    """R012：正式单据不能缺付款/交货条款。"""
    model = make_resolved_model(with_prices=True)
    model.resolved.terms = {}
    report = validate_order(model)
    assert "R012" in rule_ids(report.errors)


def test_resolved_bank_missing_swift_reports_error():
    """R013：PI/CI 必须有完整收款信息。"""
    model = make_resolved_model(with_prices=True)
    model.resolved.bank = dict(model.resolved.bank)
    model.resolved.bank["swift"] = ""
    report = validate_order(model)
    errors = {r.rule_id: r for r in report.errors}
    assert "R013" in errors
    assert "SWIFT" in errors["R013"].message


def test_resolved_bank_invalid_swift_reports_error():
    """R013：SWIFT 格式错也要拦（不只是缺）。"""
    model = make_resolved_model(with_prices=True)
    model.resolved.bank = dict(model.resolved.bank)
    model.resolved.bank["swift"] = "BAD"
    report = validate_order(model)
    errors = {r.rule_id: r for r in report.errors}
    assert "R013" in errors
    assert "8 或 11" in errors["R013"].message


def test_missing_destination_port_is_warning_not_error():
    model = make_model(with_prices=True)
    assert model.derived.port_of_destination is None
    report = validate_order(model)
    assert "R004" in rule_ids(report.warnings)
    assert "R004" not in rule_ids(report.errors)


# ── 行项目 ───────────────────────────────────────────────────────


def test_missing_price_reports_error():
    model = make_model(with_prices=False)
    report = validate_order(model)
    errors = {r.rule_id: r for r in report.errors}
    assert "R005" in errors
    # 两行都没报价，行号都应出现在说明里
    assert "1" in errors["R005"].message and "2" in errors["R005"].message


def test_zero_quantity_reports_error():
    model = make_model(with_prices=True)
    model.items[0].quantity = 0
    report = validate_order(model)
    assert "R006" in rule_ids(report.errors)


def test_missing_weight_flat_pricing_is_warning():
    # USD/PC 普通计价：缺重量不影响 PI/CI 金额，只影响 PL → warning
    model = make_model(with_prices=True, with_weights=False)
    report = validate_order(model)
    assert "R007" in rule_ids(report.warnings)
    assert "R007" not in rule_ids(report.errors)


def test_missing_weight_per_ton_pricing_is_error():
    # USD/TON 吨价：金额 = weight/1000 * price，缺重量金额算不出 → error
    model = make_model(with_prices=True, with_weights=False)
    model.order.price_unit = "USD/TON"
    report = validate_order(model)
    assert "R007" in rule_ids(report.errors)


def test_zero_price_amount_reports_error():
    model = make_model(with_prices=True)
    model.items[0].unit_price = 0.0
    report = validate_order(model)
    assert "R008" in rule_ids(report.errors)


def test_priced_per_ton_without_weight_flags_amount():
    # 单价已填但吨价缺重量 → 试算金额为 0，R008 与 R007 同时命中
    model = make_model(with_prices=True, with_weights=False)
    model.order.price_unit = "USD/TON"
    report = validate_order(model)
    assert {"R007", "R008"} <= rule_ids(report.errors)


# ── 信用证：只提醒，不判断 ───────────────────────────────────────


def test_lc_order_emits_info_only():
    model = make_model(with_prices=True)
    model.order.lc_number = "LC-2026-001"
    report = validate_order(model)
    infos = {r.rule_id: r for r in report.infos}
    assert "R009" in infos
    assert "R009" not in rule_ids(report.errors)
    assert "R009" not in rule_ids(report.warnings)
    assert "人工" in infos["R009"].message


def test_lc_keyword_in_payment_terms_emits_info():
    model = make_resolved_model(with_prices=True)
    model.resolved.terms = dict(model.resolved.terms)
    model.resolved.terms["payment"] = "100% irrevocable L/C at sight"
    report = validate_order(model)
    assert "R009" in rule_ids(report.infos)


def test_non_lc_order_has_no_lc_info():
    model = make_model(with_prices=True)
    report = validate_order(model)
    assert "R009" not in rule_ids(report.results)


# ── Reporter ─────────────────────────────────────────────────────


def test_markdown_report_renders_chinese_sections():
    model = make_model(with_prices=False)
    model.refs.seller_id = ""
    md = to_markdown(validate_order(model))
    assert "# 生成前检查报告 — 订单 TEST01" in md
    assert "## 错误（必须处理）" in md
    assert "[R001]" in md and "[R005]" in md
    assert "建议：" in md
    assert "存在错误" in md


def test_markdown_report_clean_order_says_ok():
    model = make_model(with_prices=True, with_weights=True)
    model.derived.port_of_destination = "CHICAGO, USA"
    md = to_markdown(validate_order(model))
    assert "未发现错误，可以继续生成单据" in md
    assert "## 错误" not in md


def test_text_report_renders_plain_chinese():
    model = make_model(with_prices=False)
    text = to_text(validate_order(model))
    assert "生成前检查报告 — 订单 TEST01" in text
    assert "【错误】[R005]" in text
    assert "建议：" in text
    # 纯文本不应包含 Markdown 标记
    assert "**" not in text and "##" not in text


def test_report_severity_views_partition_results():
    model = make_model(with_prices=False, with_weights=False)
    model.refs.seller_id = ""
    report = validate_order(model)
    assert len(report.errors) + len(report.warnings) + len(report.infos) == len(report.results)
    assert all(r.severity is Severity.ERROR for r in report.errors)


# ── 跨单据毛重一致校验（T1, validation/cross_doc.py）─────────────


def test_cross_doc_gw_equal_returns_none():
    """CI 与 PL 毛重相等（含 0.01 容差内）→ 无 warning。"""
    ci = {"total_gross_weight": 1234.56}
    pl = {"success": True, "total_gross_weight": 1234.56}
    assert check_ci_pl_gross_weight(ci, pl) is None
    # 容差内
    assert check_ci_pl_gross_weight({"total_gross_weight": 1234.56},
                                    {"success": True, "total_gross_weight": 1234.57}) is None


def test_cross_doc_gw_mismatch_returns_warning():
    """毛重不一致 → 返回中文 warning 文案。"""
    ci = {"total_gross_weight": 1000.00}  # 例如走了 nw*1.036 兜底
    pl = {"success": True, "total_gross_weight": 1050.00}
    msg = check_ci_pl_gross_weight(ci, pl)
    assert msg is not None
    assert "不一致" in msg


def test_cross_doc_gw_skips_when_pl_failed_or_missing():
    """任一单据缺失 / PL 未成功 → 不比对，返回 None（不误报）。"""
    ci = {"total_gross_weight": 1000.0}
    assert check_ci_pl_gross_weight(ci, None) is None
    assert check_ci_pl_gross_weight(None, {"success": True, "total_gross_weight": 1000.0}) is None
    assert check_ci_pl_gross_weight(ci, {"success": False}) is None
    assert check_ci_pl_gross_weight(ci, {"success": True, "total_gross_weight": None}) is None
