"""
validation/models.py — 生成前检查的结果数据模型

CheckResult 是单条检查结果（一条规则可产出 0..N 条）；
ValidationReport 是一次完整检查的汇总，按 severity 提供视图，
供 reporters 渲染成用户可读的中文报告。

只承载数据，不含检查逻辑（逻辑在 rules.py / engine.py）。
"""
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """检查结果级别。error 建议阻断生成；warning 建议确认；info 仅提示。"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class CheckResult:
    """单条检查结果。

    属性:
        rule_id:    规则编号，如 "R005"
        severity:   error / warning / info
        message:    给用户看的中文说明
        field:      相关字段路径（如 "refs.seller_id"、"items[].unit_price"），可为空
        suggestion: 建议用户怎么处理，可为空
    """
    rule_id: str
    severity: Severity
    message: str
    field: str | None = None
    suggestion: str | None = None


@dataclass
class ValidationReport:
    """一次生成前检查的完整结果。"""
    order_no: str
    results: list[CheckResult] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[CheckResult]:
        return [r for r in self.results if r.severity is severity]

    @property
    def errors(self) -> list[CheckResult]:
        return self.by_severity(Severity.ERROR)

    @property
    def warnings(self) -> list[CheckResult]:
        return self.by_severity(Severity.WARNING)

    @property
    def infos(self) -> list[CheckResult]:
        return self.by_severity(Severity.INFO)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
