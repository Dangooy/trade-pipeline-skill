"""
validation/reporters.py — 检查报告渲染（中文 Markdown / 纯文本）

把 ValidationReport 渲染成用户能直接读的报告。两种形态：
  - to_markdown(): 适合落盘成 .md 或在 GUI 富文本面板展示
  - to_text():     适合 CLI 终端直接 print（不依赖 Markdown 渲染器）

只做格式化，不做判断；severity 分组顺序固定为 错误 → 警告 → 提示。
"""
from trade_pipeline.validation.models import CheckResult, Severity, ValidationReport

_SECTION_ORDER = [
    (Severity.ERROR, "错误（必须处理）"),
    (Severity.WARNING, "警告（建议确认）"),
    (Severity.INFO, "提示（人工注意）"),
]

_TEXT_LABELS = {
    Severity.ERROR: "【错误】",
    Severity.WARNING: "【警告】",
    Severity.INFO: "【提示】",
}


def _summary_line(report: ValidationReport) -> str:
    counts = f"{len(report.errors)} 条错误、{len(report.warnings)} 条警告、{len(report.infos)} 条提示"
    if report.has_errors:
        return f"共发现 {counts}。存在错误，建议处理完错误项再生成 PI / CI / PL。"
    return f"共发现 {counts}。未发现错误，可以继续生成单据。"


def to_markdown(report: ValidationReport) -> str:
    """渲染成中文 Markdown 报告。"""
    lines = [
        f"# 生成前检查报告 — 订单 {report.order_no}",
        "",
        _summary_line(report),
    ]
    for severity, title in _SECTION_ORDER:
        results = report.by_severity(severity)
        if not results:
            continue
        lines += ["", f"## {title}", ""]
        for r in results:
            lines.append(f"- **[{r.rule_id}]** {r.message}")
            if r.field:
                lines.append(f"  - 相关字段：`{r.field}`")
            if r.suggestion:
                lines.append(f"  - 建议：{r.suggestion}")
    lines.append("")
    return "\n".join(lines)


def to_text(report: ValidationReport) -> str:
    """渲染成纯文本报告（CLI 终端友好）。"""
    bar = "=" * 50
    lines = [
        bar,
        f"生成前检查报告 — 订单 {report.order_no}",
        bar,
        _summary_line(report),
    ]
    for severity, title in _SECTION_ORDER:
        results = report.by_severity(severity)
        if not results:
            continue
        lines += ["", f"-- {title} --"]
        for r in results:
            lines.extend(_text_block(severity, r))
    lines.append(bar)
    return "\n".join(lines)


def _text_block(severity: Severity, r: CheckResult) -> list[str]:
    block = [f"{_TEXT_LABELS[severity]}[{r.rule_id}] {r.message}"]
    if r.field:
        block.append(f"    字段：{r.field}")
    if r.suggestion:
        block.append(f"    建议：{r.suggestion}")
    return block
