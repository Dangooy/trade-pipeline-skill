"""生成前检查接入 pipeline / CLI 的测试。

覆盖验收点：
  - 有 error 时阻断生成（price-update 路径）
  - --check-only 不生成任何单据文件
  - --no-precheck 保持旧流程（跳过检查，不落 precheck.md）
  - 正常订单（带价、无 warning）可以继续生成
  - CLI 输出包含中文检查报告
  - --skip-warnings 放行 warning，但 error 始终阻断

设计说明（v1.2.0-alpha.3 修订）：
  - 主流程 run()：报价单始终生成（缺价是先出报价单的正常状态）；但有 error 时
    **跳过 PI/CI/PL**，整体 success=False。warning 在 run() 不阻断（宽松路径）。
  - run_price_update()：带价后出正式单据的时刻，error 始终阻断、warning 默认阻断
    （--skip-warnings 放行）。packing review 在 precheck 之前应用，检查看补录后的 model。
  - 用真实流程构造 model + quotation，再跑 run/run_price_update，
    与生产路径一致，不 mock 内部行为。
"""
import os
import tempfile

import pytest

from tests.conftest import make_model
from trade_pipeline.pipeline.main import load_config, run, run_price_update
from trade_pipeline.understanding.assembler import resolve_entities
from trade_pipeline.writers.quote_writer import QuoteWriter


# ── 辅助：构造一个 price-update 可用的 (output_dir, quotation, model) ──


def _setup_priced_order(tmp_dir: str, *, with_prices: bool, clean_port: bool):
    """在 tmp_dir 下落地 model.json + quotation.xlsx，模拟报价回写前的状态。"""
    config = load_config()
    model = make_model(with_prices=with_prices, with_weights=True)
    if clean_port:
        # 消掉 R004（目的港缺失）warning，隔离出想测的信号
        model.derived.port_of_destination = "CHICAGO, USA"
    model_path = os.path.join(tmp_dir, "TEST01_model.json")
    model.to_json(model_path)

    resolved = resolve_entities(model, config)
    quote_path = os.path.join(tmp_dir, "TEST01_quotation.xlsx")
    QuoteWriter(resolved, config).write(quote_path)
    return quote_path, model_path


def _files(tmp_dir: str) -> list[str]:
    return [f for f in os.listdir(tmp_dir) if not f.startswith(".")]


# ── 有 error 时阻断生成 ──────────────────────────────────────────


def test_price_update_error_blocks_generation():
    """缺单价（R005 error）→ price-update 停止，不写 PI/CI。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=False, clean_port=True)
        result = run_price_update(quote_path, model_path)

        assert result.get("errors"), "有 error 应阻断并写入 errors"
        files = _files(tmp)
        assert not any("_pi" in f for f in files), "阻断后不应生成 PI"
        assert not any("_ci" in f for f in files), "阻断后不应生成 CI"


def test_price_update_error_blocks_even_with_skip_warnings():
    """--skip-warnings 不放过 error：缺单价仍阻断。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=False, clean_port=True)
        result = run_price_update(quote_path, model_path, skip_warnings=True)

        assert result.get("errors")
        assert not any("_pi" in f for f in _files(tmp))


# ── warning：默认阻断，--skip-warnings 放行 ──────────────────────


def test_price_update_warning_blocks_by_default():
    """带价但缺目的港（R004 warning）→ 默认阻断。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=False)
        result = run_price_update(quote_path, model_path)

        assert result.get("errors"), "warning 默认应阻断"
        assert not any("_pi" in f for f in _files(tmp))


def test_price_update_skip_warnings_passes():
    """带价 + 缺目的港 warning + --skip-warnings → 放行，生成 PI/CI。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=False)
        result = run_price_update(quote_path, model_path, skip_warnings=True)

        assert not result.get("errors"), f"放行不应有 errors: {result.get('errors')}"
        assert any("_pi" in f for f in _files(tmp)), "放行后应生成 PI"


# ── 正常订单可以继续生成 ─────────────────────────────────────────


def test_price_update_clean_order_generates_docs():
    """带价 + 无 warning → 直接放行，生成 PI/CI。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=True)
        result = run_price_update(quote_path, model_path)

        assert not result.get("errors")
        files = _files(tmp)
        assert any("_pi" in f for f in files)
        assert any("_ci" in f for f in files)


# ── --no-precheck 保持旧流程 ────────────────────────────────────


def test_no_precheck_skips_check_and_generates():
    """--no-precheck：缺价也不跑检查，旧流程照走（不落 precheck.md）。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=False, clean_port=True)
        result = run_price_update(quote_path, model_path, precheck=False)

        files = _files(tmp)
        assert not any("precheck" in f for f in files), \
            "--no-precheck 不应生成 precheck.md"
        # precheck 未拦截，PI 写入照常进行（不因 precheck 进 errors）
        assert not any("precheck" in str(e) for e in result.get("errors", []))


# ── --check-only 不生成任何单据 ─────────────────────────────────


def test_check_only_run_generates_no_documents():
    """run() --check-only：只出报告，不写 quotation/PI/CI/PL。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="CHKONLY",
            buyer_id="global_fasteners",
            output_dir=tmp,
            check_only=True,
        )
        files = _files(tmp)
        # 单据一个都不应有
        assert not any("quotation" in f for f in files)
        assert not any("_pi" in f for f in files)
        assert not any("_ci" in f for f in files)
        assert not any("_pl" in f for f in files)
        # 报告应落盘；中间产物（rfq/model）允许存在
        assert any("precheck" in f for f in files), "--check-only 应落盘 precheck 报告"
        assert "precheck_md" in result["outputs"]


def test_check_only_price_update_does_not_regenerate():
    """run_price_update() --check-only：不重新生成 PI/CI。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=True)
        run_price_update(quote_path, model_path, check_only=True)
        files = _files(tmp)
        assert not any("_pi" in f for f in files), "--check-only 不应生成 PI"
        assert not any("_ci" in f for f in files), "--check-only 不应生成 CI"


# ── Codex 复审：check_only 必须尊重 precheck 结果 ────────────────


def test_check_only_price_update_fails_on_error():
    """run_price_update() --check-only 遇 R005 error → errors 非空（不打印成功）。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=False, clean_port=True)
        result = run_price_update(quote_path, model_path, check_only=True)

        assert result.get("errors"), \
            "--check-only 遇 error 应写入 errors，不能静默成功"
        assert any("precheck" in str(e) for e in result["errors"])
        # 仍然不应生成任何单据
        assert not any("_pi" in f for f in _files(tmp))
        assert not any("_ci" in f for f in _files(tmp))


def test_cli_price_update_check_only_exits_1_on_error(monkeypatch):
    """CLI：--price-update --check-only 遇 R005 error → exit 1。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=False, clean_port=True)
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, [
                "--price-update", quote_path,
                "--model", model_path,
                "--check-only",
            ])
        assert exc.value.code == 1


def test_check_only_price_update_clean_order_no_errors():
    """对照组：带价干净订单 --check-only → 无 errors（检查通过照常成功）。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=True)
        result = run_price_update(quote_path, model_path, check_only=True)
        assert not result.get("errors"), \
            f"干净订单 --check-only 不应有 errors: {result.get('errors')}"


# ── CLI 输出包含中文检查报告 ────────────────────────────────────


def test_cli_output_contains_chinese_report(capsys):
    """run() 终端输出应包含中文检查报告（标题 + 规则编号）。"""
    with tempfile.TemporaryDirectory() as tmp:
        run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="CLICHK",
            buyer_id="global_fasteners",
            output_dir=tmp,
            check_only=True,
        )
        out = capsys.readouterr().out
        assert "生成前检查报告" in out
        assert "单价缺失" in out  # R005 在缺价 sample 上必然出现
        assert "[R005]" in out


def test_check_only_writes_markdown_report():
    """--check-only 落盘的 precheck.md 内容是中文 Markdown 报告。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="MDCHK",
            buyer_id="global_fasteners",
            output_dir=tmp,
            check_only=True,
        )
        md_path = result["outputs"]["precheck_md"]
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# 生成前检查报告" in content
        assert "## 错误（必须处理）" in content


# ── CLI argparse 入口：三个新标志能解析并透传 ────────────────────


def _run_main(monkeypatch, argv):
    import sys

    from trade_pipeline.pipeline.main import main
    monkeypatch.setattr(sys, "argv", ["trade_pipeline"] + argv)
    main()


def test_cli_check_only_flag_exits_clean_on_warnings(monkeypatch):
    """--check-only 经 CLI 入口：sample 有 error → exit(1)（脚本可据退出码判断）。"""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, [
                "--input", "examples/sample_inquiry.xlsx",
                "--order", "CLI_CHECK_ONLY",
                "--buyer", "global_fasteners",
                "--output-dir", tmp,
                "--check-only",
            ])
        # sample 缺价 → check_only success=False → exit 1
        assert exc.value.code == 1
        assert not any("_pi" in f for f in _files(tmp))


def test_cli_no_precheck_flag_runs_old_flow(monkeypatch):
    """--no-precheck 经 CLI 入口：主流程照常成功，不落 precheck.md。"""
    with tempfile.TemporaryDirectory() as tmp:
        _run_main(monkeypatch, [
            "--input", "examples/sample_inquiry.xlsx",
            "--order", "CLI_NO_PRECHECK",
            "--buyer", "global_fasteners",
            "--output-dir", tmp,
            "--quote-only",
            "--no-precheck",
        ])
        assert not any("precheck" in f for f in _files(tmp))


# ── P1-a：run() 有 error 时出报价单、跳过 PI/CI/PL ───────────────


def test_run_error_emits_quotation_skips_pi_ci():
    """run() 缺价 sample → 报价单生成，PI/CI 跳过，success=False，errors 含 R005。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="RUNERR",
            buyer_id="global_fasteners",
            output_dir=tmp,
        )
        assert result["success"] is False
        assert "quotation_xlsx" in result["outputs"]
        assert any("quotation" in f for f in _files(tmp))
        assert not any("_pi" in f for f in _files(tmp)), "error 阻断后不应生成 PI"
        assert not any("_ci" in f for f in _files(tmp)), "error 阻断后不应生成 CI"
        assert any("R005" in e for e in result["errors"]), "应记录 R005 阻断错误"


def test_run_no_precheck_generates_pi_ci_despite_missing_price():
    """逃生舱：run(precheck=False) 缺价 sample 仍出 PI/CI（旧流程兼容）。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="RUNESC",
            buyer_id="global_fasteners",
            output_dir=tmp,
            precheck=False,
        )
        assert result["success"] is True
        assert any("_pi" in f for f in _files(tmp)), "precheck=False 应照出 PI"
        assert any("_ci" in f for f in _files(tmp)), "precheck=False 应照出 CI"
        assert not any("precheck" in f for f in _files(tmp)), "不应落 precheck.md"


# ── P2：check_only + skip_warnings 遇 error 仍失败 ──────────────


def test_check_only_skip_warnings_still_fails_on_error():
    """run() --check-only --skip-warnings 缺价 → error 不被放过，success=False。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="CHKSKIP",
            buyer_id="global_fasteners",
            output_dir=tmp,
            check_only=True,
            skip_warnings=True,
        )
        assert result["success"] is False, "error 不应被 skip_warnings 放过"


# ── P1-b：price-update 先应用 packing review 再检查 ─────────────


def test_price_update_packing_review_clears_ton_weight_error(monkeypatch):
    """吐价订单缺重量（R007 error），传补重量 review → 先补录再检查 → 不再被拦，PI/CI 生成。

    验证 P1-b：packing review 必须在 precheck 之前应用，检查看补录后的最终 model。
    monkeypatch config_path 到 temp，避免 product_catalog 自动学习污染真实 config。
    """
    from trade_pipeline.validation.packing_review import (
        PackingReview, PackingReviewItem,
    )

    with tempfile.TemporaryDirectory() as tmp:
        # config_path 指向 temp，隔离 catalog 写入
        fake_config = os.path.join(tmp, "config.yaml")
        config = load_config()
        import yaml
        with open(fake_config, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)
        monkeypatch.setattr(
            "trade_pipeline.pipeline.main.config_path", lambda: fake_config)

        # 构造吐价 + 缺重量订单（R007 升级为 error）
        model = make_model(with_prices=True, with_weights=False)
        model.order.price_unit = "USD/TON"
        model.derived.port_of_destination = "CHICAGO, USA"  # 消掉 R004
        model_path = os.path.join(tmp, "TEST01_model.json")
        model.to_json(model_path)

        resolved = resolve_entities(model, config)
        quote_path = os.path.join(tmp, "TEST01_quotation.xlsx")
        QuoteWriter(resolved, config).write(quote_path)

        # 补重量 review（item_uuid 对齐 make_model 的两行）
        review = PackingReview(order_no="TEST01", items=[
            PackingReviewItem(
                item_uuid="abc123def456", description="HEX HEAD BOLT DIN 933 M8x25 ZP",
                quantity=50000, unit="pcs", kg_per_1000pcs=5.8, resolved=True),
            PackingReviewItem(
                item_uuid="xyz789ghi012", description="HEX NUT DIN 934 M8 ZP",
                quantity=100000, unit="pcs", kg_per_1000pcs=2.8, resolved=True),
        ])
        review_path = os.path.join(tmp, "TEST01_packing_review.json")
        review.to_json(review_path)

        result = run_price_update(
            quote_path, model_path, packing_review_path=review_path)

        # 补重量后 R007 清除 → 不阻断 → PI/CI 生成
        assert not result.get("errors"), f"补重量后不应被拦: {result.get('errors')}"
        assert any("_pi" in f for f in _files(tmp)), "补重量后应生成 PI"
        assert any("_ci" in f for f in _files(tmp)), "补重量后应生成 CI"


# ── Codex 复审：run() 最终 precheck.md 须反映补录后的 model ──────


def test_run_packing_review_final_precheck_md_reflects_updated_model():
    """run() 带 packing_review_path：最终落盘的 precheck.md 不应保留补录前
    的旧报告（R007 重量缺失在补录后应消失；R005 缺价仍在）。"""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        # 第一遍：precheck=False 走老流程，让 PL 安全网生成 packing_review.json
        # （sample 缺价，precheck=True 会因 R005 阻断 PI/CI/PL，review 无从生成）
        first = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="MDUPD",
            buyer_id="global_fasteners",
            output_dir=tmp,
            precheck=False,
        )
        review_path = first["outputs"].get("packing_review_json")
        assert review_path, "缺重量 sample 应生成 packing_review.json"

        # 模拟用户补录重量
        with open(review_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for it in data["items"]:
            it["kg_per_1000pcs"] = 5.0
            it["pcs_per_carton"] = 1000
            it["resolved"] = True
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        # 第二遍：precheck 默认开 + 带 review → 最终 precheck.md 应是补录后状态
        second = run(
            input_path="examples/sample_inquiry.xlsx",
            order_no="MDUPD",
            buyer_id="global_fasteners",
            output_dir=tmp,
            packing_review_path=review_path,
            save_packing_to_catalog=False,  # 不污染主 config 的 catalog
        )

        md_path = second["outputs"]["precheck_md"]
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "R007" not in content, (
            "补录重量后，最终 precheck.md 不应再含 R007 重量缺失"
            "（说明落盘的是补录前的旧报告）"
        )
        assert "R005" in content, "缺价 R005 与补录无关，应仍在最终报告中"


# ── 任务卡 #3.5：run_price_update 结构化返回 ────────────────────


def test_price_update_returns_structured_precheck_report():
    """run_price_update 返回 precheck_report，可直接判断 error/warning（不靠文案）。

    缺目的港（R004 warning）→ has_errors=False / has_warnings=True；
    每条 warning 含 rule_id + message。GUI 据此精确区分阻断类型。
    """
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=False)  # 缺目的港 → R004 warning
        result = run_price_update(quote_path, model_path)

        report = result.get("precheck_report")
        assert report is not None, "应返回结构化 precheck_report"
        assert report["has_errors"] is False
        assert report["has_warnings"] is True
        assert all("rule_id" in w and "message" in w for w in report["warnings"]), \
            "每条 warning 应含 rule_id + message"
        # 既有键不变（CLI 兼容性）：warning 默认阻断仍写 errors
        assert result.get("errors"), "warning 默认阻断的既有行为不变"


def test_price_update_structured_report_clean_order():
    """干净订单（带价 + 目的港）→ precheck_report has_errors/has_warnings 均 False。"""
    with tempfile.TemporaryDirectory() as tmp:
        quote_path, model_path = _setup_priced_order(
            tmp, with_prices=True, clean_port=True)
        result = run_price_update(quote_path, model_path)

        report = result.get("precheck_report")
        assert report is not None
        assert report["has_errors"] is False
        assert report["has_warnings"] is False


def test_price_update_pl_missing_weight_generates_review_json(monkeypatch):
    """PL 缺重量（非 TON 计价，过 precheck 但 PL 写入缺重量）→ run_price_update
    生成 packing_review.json 并写进 outputs，让 GUI 能接 Gateway（任务卡 #3.5）。

    monkeypatch config_path 隔离 catalog 写入。
    """
    with tempfile.TemporaryDirectory() as tmp:
        fake_config = os.path.join(tmp, "config.yaml")
        config = load_config()
        import yaml
        with open(fake_config, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)
        monkeypatch.setattr(
            "trade_pipeline.pipeline.main.config_path", lambda: fake_config)

        # 带价 + 缺重量 + 普通单价（非 TON，故缺重量不在 precheck 触发 R007 error）
        # + 目的港齐全（消 R004）→ 过 precheck，走到 PL 写入时才因缺重量失败
        model = make_model(with_prices=True, with_weights=False)
        model.derived.port_of_destination = "CHICAGO, USA"
        model_path = os.path.join(tmp, "TEST01_model.json")
        model.to_json(model_path)

        resolved = resolve_entities(model, config)
        quote_path = os.path.join(tmp, "TEST01_quotation.xlsx")
        QuoteWriter(resolved, config).write(quote_path)

        result = run_price_update(quote_path, model_path, skip_warnings=True)

        # PI/CI 应生成（缺重量不阻断它们）；PL 缺重量 → 生成 review.json
        assert "packing_review_json" in result.get("outputs", {}), \
            "PL 缺重量应生成 packing_review.json 供 GUI 接 Gateway"
        review_p = result["outputs"]["packing_review_json"]
        assert os.path.exists(review_p), "review.json 文件应实际落盘"
        # PL 本身未生成
        assert not any("_pl" in f for f in _files(tmp)), "缺重量时 PL 不应生成"
