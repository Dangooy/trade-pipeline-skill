"""CLI entry-point tests for trade_pipeline.pipeline.main:main().

覆盖 argparse 入口的关键分支：
- --price-update 缺 --model → exit 1
- 缺 --input/--order → 打印 help + exit 1
- 正常 --quote-only 路径 → 成功不抛
- pipeline 失败时 exit 1

不动业务代码：只 monkey-patch sys.argv，不修改任何 main.py 内部行为。
"""
import sys
import tempfile

import pytest

from trade_pipeline.pipeline.main import main


def _run_main_with_argv(monkeypatch, argv: list[str]):
    """把 argv 注入 sys.argv 后调 main()。"""
    monkeypatch.setattr(sys, "argv", ["trade_pipeline"] + argv)
    main()


def test_main_missing_input_and_order_exits_1(monkeypatch, capsys):
    """裸跑 main() 不带 --input/--order → print_help + exit(1)。"""
    with pytest.raises(SystemExit) as exc:
        _run_main_with_argv(monkeypatch, [])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    # argparse 的 help 会写入 stdout，包含 usage 字样
    assert "usage" in captured.out.lower() or "usage" in captured.err.lower()


def test_main_price_update_without_model_exits_1(monkeypatch, capsys):
    """--price-update 但不带 --model → 报错 + exit(1)。"""
    with pytest.raises(SystemExit) as exc:
        _run_main_with_argv(monkeypatch, ["--price-update", "fake_quote.xlsx"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--model" in captured.out


def test_main_quote_only_happy_path(monkeypatch):
    """--quote-only 模式跑通 → main() 正常返回不抛。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _run_main_with_argv(monkeypatch, [
            "--input", "examples/sample_inquiry.xlsx",
            "--order", "CLI_QUOTE_ONLY",
            "--buyer", "global_fasteners",
            "--output-dir", tmp_dir,
            "--quote-only",
        ])
        # 没抛 SystemExit 即视为 success


def test_main_full_pipeline_missing_price_exits_1(monkeypatch):
    """完整跑 sample（缺单价）→ R005 error 阻断正式单据 → run() success=False
    → main() exit(1)。报价单仍生成，但 PI/CI/PL 被跳过。

    （旧名 test_main_full_pipeline_with_packing_warning_succeeds：v1.2.0-alpha.3
    起，缺价订单走完整流程会被生成前检查拦截，不再静默成功。）
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(SystemExit) as exc:
            _run_main_with_argv(monkeypatch, [
                "--input", "examples/sample_inquiry.xlsx",
                "--order", "CLI_FULL",
                "--buyer", "global_fasteners",
                "--output-dir", tmp_dir,
            ])
        assert exc.value.code == 1


def test_main_nonexistent_input_exits_1(monkeypatch):
    """--input 指向不存在文件 → pipeline 返回 errors → exit(1)。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(SystemExit) as exc:
            _run_main_with_argv(monkeypatch, [
                "--input", "examples/__cli_test_missing__.xlsx",
                "--order", "CLI_MISSING",
                "--buyer", "global_fasteners",
                "--output-dir", tmp_dir,
            ])
        assert exc.value.code == 1


def test_main_no_catalog_save_flag(monkeypatch):
    """--no-catalog-save 透传到 run() 不报错。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _run_main_with_argv(monkeypatch, [
            "--input", "examples/sample_inquiry.xlsx",
            "--order", "CLI_NO_CAT",
            "--buyer", "global_fasteners",
            "--output-dir", tmp_dir,
            "--quote-only",
            "--no-catalog-save",
        ])
