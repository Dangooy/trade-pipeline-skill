"""出单前预算装箱（B-1）测试。

背景：修复前，CI 读 `model.derived` 里的装箱数，而那是 **PL 回写**的 —— 于是
CI 必须排在 PL 之后才有真值（public 的 T1 修复就是靠调顺序）。B-1 改成
**出单前先算一遍装箱、写进 derived**，让 PI/CI/PL 都从同一份取数，顺序因此
不再影响数字。

本文件覆盖四件事：

1. **同源**：预算算出的数与 PL writer 算出的一致（两者现在走同一函数）
2. **顺序无关**：先跑预算后，即使 PL 不跑，CI 也能拿到真值（而不是 1.036 估算）
3. **fail-loud**：重量齐全却算崩 → 不出正式单据，绝不用可能错的数字继续
4. **诚实边界**：重量不全导致预算跳过时，CI 必须标记其毛重为估算值（选项 A）
"""

from __future__ import annotations

import copy
import os
import tempfile

import pytest

from tests.conftest import SAMPLE_CONFIG, make_resolved_model
from trade_pipeline.writers.ci_writer import CIWriter
from trade_pipeline.writers.pl_writer_lite import (
    PLWriterLite,
    apply_packing_summary_to_derived,
    compute_packing_summary,
    resolve_packing_params,
)


def _import_main():
    from trade_pipeline.pipeline import main as pipeline_main

    return pipeline_main


# ─────────────────────────────────────────────────────────────
# 参数解析优先级（review.pallet > config.packing > 模块默认值）
# ─────────────────────────────────────────────────────────────


def test_resolve_params_uses_config_when_no_review():
    cfg = {"packing": {"carton_weight_kg": 20, "cartons_per_pallet": 12,
                       "pallet_self_weight_kg": 30, "measurement_per_pallet_m3": 0.6}}
    params = resolve_packing_params(cfg, None)
    assert params == {
        "kg_per_carton": 20,
        "cartons_per_pallet": 12,
        "pallet_self_weight_kg": 30,
        "measurement_per_pallet_m3": 0.6,
    }


def test_resolve_params_falls_back_to_module_defaults():
    """空 config 时用模块默认值，而不是崩。"""
    params = resolve_packing_params({}, None)
    assert params["kg_per_carton"] > 0
    assert params["cartons_per_pallet"] > 0
    assert params["pallet_self_weight_kg"] > 0


def test_resolve_params_review_overrides_config():
    """人工补录的装箱参数（review.pallet）必须压过 config。"""

    class _Pallet:
        cartons_per_pallet = 7
        self_weight_kg = 11.0

    class _Review:
        pallet = _Pallet()

    cfg = {"packing": {"cartons_per_pallet": 36, "pallet_self_weight_kg": 28}}
    params = resolve_packing_params(cfg, _Review())
    assert params["cartons_per_pallet"] == 7
    assert params["pallet_self_weight_kg"] == 11.0


# ─────────────────────────────────────────────────────────────
# 单一入口：PL writer 与预算算出的必须是同一份数
# ─────────────────────────────────────────────────────────────


def test_prebudget_and_pl_writer_agree():
    """两者走同一函数 → 同一输入必得同一输出。（同源的基础）"""
    model_a = make_resolved_model(with_prices=True, with_weights=True)
    model_b = make_resolved_model(with_prices=True, with_weights=True)

    _, summary_from_budget = compute_packing_summary(model_a.items, SAMPLE_CONFIG)

    with tempfile.TemporaryDirectory() as tmp:
        pl_result = PLWriterLite(model_b, SAMPLE_CONFIG).write(os.path.join(tmp, "pl.xlsx"))

    assert summary_from_budget["total_net_weight"] == pl_result["total_net_weight"]
    assert summary_from_budget["total_gross_weight"] == pl_result["total_gross_weight"]
    assert summary_from_budget["total_pallets"] == pl_result["total_pallets"]
    assert summary_from_budget["total_cartons"] == pl_result["total_cartons"]


def test_apply_summary_only_touches_packing_fields():
    """回写只该动装箱那 5 个字段 —— 不能把 assemble 填的 total_qty / port_* 覆盖掉。"""
    model = make_resolved_model(with_prices=True, with_weights=True)
    model.derived.total_qty = 12345
    model.derived.port_of_loading = "QINGDAO,CHINA"
    model.derived.port_of_destination = "CHICAGO, USA"
    model.derived.has_weight = True

    _, summary = compute_packing_summary(model.items, SAMPLE_CONFIG)
    apply_packing_summary_to_derived(model, summary)

    assert model.derived.total_qty == 12345
    assert model.derived.port_of_loading == "QINGDAO,CHINA"
    assert model.derived.port_of_destination == "CHICAGO, USA"
    assert model.derived.has_weight is True
    # 而装箱字段确实被写了
    assert model.derived.total_net_weight == summary["total_net_weight"]
    assert model.derived.pallet_count == summary["total_pallets"]


# ─────────────────────────────────────────────────────────────
# 顺序无关：这是 B-1 相对 T1 的实质改进
# ─────────────────────────────────────────────────────────────


def test_ci_gets_true_gross_even_when_pl_never_runs():
    """先跑出单前预算 → 即使 PL 完全没跑，CI 也应拿到真值而不是 1.036 估算。

    这正是修复前必须靠「PL 先于 CI」才能达成的事——现在靠预算达成，与顺序无关。
    """
    model = make_resolved_model(with_prices=True, with_weights=True)

    # 出单前预算（pipeline 在生成任何单据前会做这一步）
    _, summary = compute_packing_summary(model.items, SAMPLE_CONFIG)
    apply_packing_summary_to_derived(model, summary)

    # 故意不跑 PL，直接跑 CI
    with tempfile.TemporaryDirectory() as tmp:
        ci_info = CIWriter(model, SAMPLE_CONFIG).write(os.path.join(tmp, "ci.xlsx"))

    assert ci_info["gross_from_budget"] is True, "CI 应读到预算写入的真值"
    assert ci_info["total_gross_weight"] == summary["total_gross_weight"]

    nw = ci_info["total_net_weight"]
    assert ci_info["total_gross_weight"] != round(nw * 1.036, 2), (
        "若与 1.036 估算相等，说明 CI 仍走了兜底（真值恰好撞上也会导致误判，"
        "故同时断言 gross_from_budget 标记）"
    )


def test_ci_without_prebudget_flags_estimate():
    """没跑预算（重量不全）时，CI 必须把毛重标记为估算值。

    这类估算毛重会印在正式单据上，用户有权知道它不是真值。
    """
    model = make_resolved_model(with_prices=True, with_weights=True)
    model.derived.total_net_weight = None
    model.derived.total_gross_weight = None

    with tempfile.TemporaryDirectory() as tmp:
        ci_info = CIWriter(model, SAMPLE_CONFIG).write(os.path.join(tmp, "ci.xlsx"))

    assert ci_info["gross_from_budget"] is False
    nw = ci_info["total_net_weight"]
    assert ci_info["total_gross_weight"] == round(nw * 1.036, 2)


# ─────────────────────────────────────────────────────────────
# fail-loud：重量齐全却算崩 → 不出正式单据
# ─────────────────────────────────────────────────────────────


def test_prebudget_failure_blocks_formal_documents(monkeypatch):
    """重量齐全但装箱参数非法时，pipeline 必须报 error 且不出 PI/PL/CI。"""
    pipeline_main = _import_main()

    tmp_cfg = os.path.join(tempfile.mkdtemp(), "config.yaml")
    import yaml

    cfg = copy.deepcopy(SAMPLE_CONFIG)
    cfg.setdefault("packing", {})["cartons_per_pallet"] = 0  # 触发 _compute_packing 的正当性守卫
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)

    import pathlib

    monkeypatch.setattr(pipeline_main, "config_path", lambda: pathlib.Path(tmp_cfg))

    model = make_resolved_model(with_prices=True, with_weights=True)
    with tempfile.TemporaryDirectory() as tmp:
        results = pipeline_main._write_trade_docs(
            model, cfg, tmp, "B1FAIL", total_steps=8)

    assert results["errors"], "预算失败应记 error"
    assert any("出单前装箱预算失败" in e for e in results["errors"])
    assert not results["outputs"].get("pi_xlsx"), "预算失败后不应生成 PI"
    assert not results["outputs"].get("pl_xlsx"), "预算失败后不应生成 PL"
    assert not results["outputs"].get("ci_xlsx"), "预算失败后不应生成 CI"


def test_prebudget_skipped_when_weight_incomplete():
    """重量不全时预算不跑（交给 PL 的 review 流程），且不应报 error。"""
    pipeline_main = _import_main()
    from tests.conftest import make_model

    model = make_model(with_prices=True, with_weights=False)
    model.resolved = make_resolved_model(with_prices=True, with_weights=True).resolved

    with tempfile.TemporaryDirectory() as tmp:
        results = pipeline_main._write_trade_docs(
            model, SAMPLE_CONFIG, tmp, "B1SKIP", total_steps=8,
            packing_review=None,
        )

    # 重量不全 → 预算跳过（不报"预算失败"这类错）
    assert not any("出单前装箱预算失败" in e for e in results.get("errors", []))


def test_compute_packing_summary_raises_on_missing_weight():
    """缺重量时应抛 PackingInfoMissingError（与 PL 原行为一致，不做静默降级）。"""
    from tests.conftest import make_model
    from trade_pipeline.writers.pl_writer_lite import PackingInfoMissingError

    model = make_model(with_prices=True, with_weights=False)
    with pytest.raises(PackingInfoMissingError):
        compute_packing_summary(model.items, SAMPLE_CONFIG)


def test_compute_packing_summary_allow_missing_weight_optout():
    """显式 allow_missing_weight=True 时跳过检查（demo / 测试用）。"""
    from tests.conftest import make_model

    model = make_model(with_prices=True, with_weights=False)
    lines, summary = compute_packing_summary(
        model.items, SAMPLE_CONFIG, allow_missing_weight=True
    )
    assert isinstance(summary, dict)
    assert "total_gross_weight" in summary
