"""
validation/engine.py — 生成前检查引擎

入口只有一个：validate_order(model) -> ValidationReport。
遍历规则注册表，把所有 CheckResult 汇总成一份报告。引擎本身
不做任何判断（判断都在 rules.py），也不阻断流程——是否因
error 停止生成，由调用方（main.py / GUI）决定。

预期接入点（本轮不接）：pipeline/main.py 在 resolve_entities 之后、
各 Writer 之前调用，把报告渲染给用户（见 reporters.py）。
"""
from collections.abc import Callable

from trade_pipeline.models.order_model import OrderModel
from trade_pipeline.validation.models import CheckResult, ValidationReport
from trade_pipeline.validation.rules import ALL_RULES

Rule = Callable[[OrderModel], list[CheckResult]]


def validate_order(model: OrderModel, rules: list[Rule] | None = None) -> ValidationReport:
    """对 OrderModel 跑一轮生成前检查，返回汇总报告。

    参数:
        model: 已组装的订单模型（resolve_entities 前后均可；
               未 resolve 时 R009 只看 lc_number 信号）
        rules: 自定义规则列表，默认用 rules.ALL_RULES 全量
    """
    active = ALL_RULES if rules is None else rules
    results: list[CheckResult] = []
    for rule in active:
        results.extend(rule(model))
    return ValidationReport(order_no=model.order.order_no, results=results)
