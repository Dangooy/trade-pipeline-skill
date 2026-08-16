"""validation/cross_doc.py — 跨单据一致性校验（T1）

与 rules.py 的单模型规则不同，这里的校验需要"多份单据的产出"才能判断，
故不放进 validate_order(model) 的规则注册表，而由 pipeline 在两份单据都
生成后调用。规则理念一致：纯函数、不改数据、发现不一致就返回可读消息。

当前两条：CI 页脚毛重必须等于 PL 汇总毛重；CI 页脚净重必须等于 PL 汇总净重（B3）。

背景：PLWriterLite 是唯一按托盘数算真实毛重（净重 + 托盘数 × 托盘自重）并
回写 model.derived.total_gross_weight 的环节；CI 页脚 G.W. 读该真值，PL 缺失
时才走 nw*1.036 兜底。若 CI 先于 PL 生成，derived 恒为 None → CI 永远走兜底，
与 PL 系统性不一致。修复后（PL 先于 CI）二者应严格相等，本校验是回归护栏。
"""

# 毛重比对容差（kg）：两个 writer 各自 round(…, 2)，允许 0.01 舍入误差。
GROSS_WEIGHT_TOLERANCE_KG = 0.01
# 净重比对容差（kg）：同上（B3 后 CI 读 PL 回写值,应严格相等,容差仅为防御）。
NET_WEIGHT_TOLERANCE_KG = 0.01


def check_ci_pl_gross_weight(ci_info: dict | None, pl_result: dict | None) -> str | None:
    """比对 CI 与 PL 的毛重，不一致时返回一条中文 warning，一致 / 无从比对返回 None。

    参数:
        ci_info:   CIWriter.write() 的返回 dict（含 total_gross_weight）
        pl_result: PLWriter.write() 的返回 dict（含 success / total_gross_weight）

    仅在两份单据都成功生成、且都带毛重时比对；任一缺失 / PL 未成功则跳过，
    避免在"本就没生成某单据"的正常场景下误报。
    """
    if not ci_info or not pl_result or not pl_result.get("success"):
        return None
    ci_gw = ci_info.get("total_gross_weight")
    pl_gw = pl_result.get("total_gross_weight")
    if ci_gw is None or pl_gw is None:
        return None
    if abs(ci_gw - pl_gw) > GROSS_WEIGHT_TOLERANCE_KG:
        return (
            f"CI 毛重 ({ci_gw:,.2f}kg) 与 PL 毛重 ({pl_gw:,.2f}kg) 不一致，"
            "请核对：CI 可能走了 nw*1.036 兜底而未读到 PL 回写的真值。"
        )
    return None


def check_ci_pl_net_weight(ci_info: dict | None, pl_result: dict | None) -> str | None:
    """比对 CI 与 PL 的净重（B3），语义与毛重校验一致。

    B3 后 CI 页脚 N.W. 优先读 PL 回写的 model.derived.total_net_weight，
    两单应严格相等；本校验是"CI 又变回独立累加"这类回归的护栏。
    """
    if not ci_info or not pl_result or not pl_result.get("success"):
        return None
    ci_nw = ci_info.get("total_net_weight")
    pl_nw = pl_result.get("total_net_weight")
    if ci_nw is None or pl_nw is None:
        return None
    if abs(ci_nw - pl_nw) > NET_WEIGHT_TOLERANCE_KG:
        return (
            f"CI 净重 ({ci_nw:,.2f}kg) 与 PL 净重 ({pl_nw:,.2f}kg) 不一致，"
            "请核对：CI 可能未读到 PL 回写的 total_net_weight。"
        )
    return None
