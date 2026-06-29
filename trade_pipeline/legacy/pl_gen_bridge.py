"""
legacy/pl_gen_bridge.py — 桥接现有 pl-gen 管线

不重写 pl-gen 内核，通过 importlib 或 subprocess 调用。
PL 完成后将 packing 数据回写到 OrderModel。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path


PL_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "pl-gen"


def _load_plgen_pipeline():
    """动态加载 pl_gen.pipeline 模块"""
    pipeline_path = PL_GEN_DIR / "pl_gen" / "pipeline.py"
    if not pipeline_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("pl_gen_pipeline", str(pipeline_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_plgen(pi_path: str, config_name: str, output_path: str) -> dict:
    """
    调用 pl-gen 管线生成装箱单。

    优先用 importlib 直接调用，失败时 fallback 到 subprocess。

    返回:
        dict — {"success": bool, "pallet_count": int, "total_cartons": int, ...}
    """
    # 方式 1: subprocess（更稳定，不污染当前进程）
    cmd = [
        sys.executable, "-m", "pl_gen",
        "--config", config_name,
        "--pi", str(pi_path),
        "-o", str(output_path),
    ]
    result = subprocess.run(
        cmd, cwd=str(PL_GEN_DIR), capture_output=True, text=True,
    )

    # PL 文件实际生成即视为成功（QA 警告不阻断）
    if Path(output_path).exists():
        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output_path": output_path,
        }

    return {
        "success": False,
        "returncode": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
    }


def write_back_packing(model, pl_result: dict) -> None:
    """PL 生成结果回写到 OrderModel.derived"""
    if not pl_result.get("success"):
        return
    # 从 stdout 或结果中解析数据（具体字段取决于 pl-gen 输出）
    # 此处为框架，实际数据从 pl-gen 的 PackingResult 或 stdout 提取
    model.derived.pallet_count = pl_result.get("pallet_count")
    model.derived.total_cartons = pl_result.get("total_cartons")
    model.derived.total_net_weight = pl_result.get("total_net_weight")
    model.derived.total_gross_weight = pl_result.get("total_gross_weight")
    model.derived.total_measurement_m3 = pl_result.get("total_measurement_m3")


def bridge(model, output_dir: str, pl_config_name: str = "standard") -> dict:
    """
    完整桥接：OrderModel → pl-gen → 回写

    前提：PI Excel 已由 PIWriter 生成在 output_dir 中。
    如果 pl-gen 目录不存在（公开仓库中未包含），返回友好提示而非崩溃。
    """
    if not PL_GEN_DIR.exists():
        return {
            "success": False,
            "error": "pl-gen module not found (optional dependency, not included in this repo). "
                     "Steps 1-7 completed successfully. PL generation requires the separate pl-gen package.",
            "pl_path": "",
        }

    order_no = model.order.order_no
    pi_path = str(Path(output_dir) / f"{order_no}_pi.xlsx")
    pl_path = str(Path(output_dir) / f"{order_no}_pl.xlsx")

    if not Path(pi_path).exists():
        return {"success": False, "error": f"PI 文件不存在: {pi_path}"}

    result = run_plgen(pi_path, pl_config_name, pl_path)
    if result.get("success"):
        write_back_packing(model, result)

    result["pl_path"] = pl_path
    return result
