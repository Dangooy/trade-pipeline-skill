"""业务时区（defaults.business_timezone）测试。

背景：`order.date` 会直接印在报价单 / PI / CI / PL 上。旧实现用裸
`datetime.now()`，取的是**运行机器**的时区；生产环境常是 UTC 服务器或
CI runner，而 Asia/Shanghai 是 UTC+8、Asia/Tokyo 是 UTC+9 —— 当地当天
00:00 到 08:00/09:00 之间生成的单据会被印成**前一天**。

修复方式：`config.defaults.business_timezone` 可配（IANA 名称），
未配置时保持旧的本地时区行为；配了非法值则响亮失败，不静默回退 ——
静默回退会重新制造「日期跟着运行环境走」这个正被修复的 bug。

测试用「把宿主机冻结成一台 UTC 机器」的方式判定新旧行为：只有当注入的
时刻跨日历日时才有判别力，故固定取 UTC 23:30（业务时区已是次日）。
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml

from tests.conftest import SAMPLE_CONFIG
from trade_pipeline.understanding import assembler
from trade_pipeline.understanding.assembler import assemble, resolve_business_tz

# 宿主机被冻结在这一刻：UTC 2026-07-26 23:30
# → UTC 当天是 26 July；Asia/Shanghai(UTC+8) / Asia/Tokyo(UTC+9) 已是 27 July
FROZEN_UTC = datetime(2026, 7, 26, 23, 30, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """把宿主机固定成一台 UTC 机器。

    tz=None 这一支模拟旧实现的裸 now()：返回宿主机本地时间且不带 tzinfo。
    这里宿主机就是 UTC，所以是 26 日 23:30 —— 与 tz 感知那支的 27 日
    08:30(JST) 分属两个日历日，新旧实现由此可判。

    注意不能写成 astimezone()（无参），那会转成真实本机时区；开发机若在
    亚洲时区，旧实现也会印 27 July，测试便恒过。
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_UTC.replace(tzinfo=None)
        return FROZEN_UTC.astimezone(tz)


@pytest.fixture
def frozen_utc_host(monkeypatch):
    monkeypatch.setattr(assembler, "datetime", _FrozenDatetime)
    return _FrozenDatetime


def _config_with_tz(value):
    cfg = copy.deepcopy(SAMPLE_CONFIG)
    cfg.setdefault("defaults", {})["business_timezone"] = value
    return cfg


def _assemble(config):
    rfq = {
        "buyer_name_en": "Global Fasteners LLC",
        "currency": "USD",
        "price_unit": "USD/PC",
        "format": "standard",
        "items": [{"description": "DIN125 WASHER M8", "quantity": 1000, "unit": "pcs"}],
        "source_file": "x.xlsx",
    }
    return assemble(rfq=rfq, config=config, order_no="T1",
                    hint_buyer_id="global_fasteners")


# ─────────────────────────────────────────────────────────────
# resolve_business_tz 单元
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"defaults": {}},
        {"defaults": {"business_timezone": None}},
        {"defaults": {"business_timezone": ""}},
        {"defaults": {"port_of_loading": "QINGDAO,CHINA"}},
    ],
    ids=["空配置", "defaults为空", "值为null", "值为空串", "无该键"],
)
def test_unset_returns_none(config):
    """未配置时返回 None —— 调用方据此沿用宿主机本地时区（与旧行为一致）。"""
    assert resolve_business_tz(config) is None


@pytest.mark.parametrize(
    "name",
    ["Asia/Shanghai", "Asia/Tokyo", "Europe/London", "Australia/Sydney", "UTC"],
)
def test_valid_name_returns_zoneinfo(name):
    tz = resolve_business_tz({"defaults": {"business_timezone": name}})
    assert isinstance(tz, ZoneInfo)
    assert str(tz) == name


@pytest.mark.parametrize("bad", ["Asia/Nowhere", "Not/AZone", "上海", 123])
def test_invalid_name_fails_loudly(bad):
    """非法时区名必须响亮失败。

    静默回退到本地时区会重新制造「日期跟着运行环境走」这个正被修复的 bug，
    而单据日期错了在清关和收汇上都是实际问题 —— 宁可让配置错误当场暴露。
    """
    with pytest.raises(ValueError) as exc:
        resolve_business_tz({"defaults": {"business_timezone": bad}})
    msg = str(exc.value)
    assert "business_timezone" in msg, "错误信息必须点名是哪个配置项"
    assert "IANA" in msg, "错误信息应说明期望的格式"


# ─────────────────────────────────────────────────────────────
# 走真实 assemble() 路径的集成验证
# ─────────────────────────────────────────────────────────────


def test_configured_timezone_survives_utc_host(frozen_utc_host):
    """配了业务时区后，单据日期必须是业务所在地那一天，与宿主机时区无关。

    这是本次修复的核心断言：宿主机是 UTC 的 26 日 23:30，但上海已是 27 日。
    """
    model = _assemble(_config_with_tz("Asia/Shanghai"))
    assert model.order.date == "27 July 2026", (
        f"UTC 宿主机 23:30 时，上海日期应为 27 July 2026，实得 {model.order.date}"
    )


def test_unset_timezone_keeps_legacy_local_behaviour(frozen_utc_host):
    """不配置时保持旧行为（跟宿主机走）—— 向后兼容，不悄悄改用户的结果。"""
    cfg = copy.deepcopy(SAMPLE_CONFIG)
    cfg.get("defaults", {}).pop("business_timezone", None)
    model = _assemble(cfg)
    assert model.order.date == "26 July 2026", (
        f"未配置时应沿用宿主机（UTC）日期 26 July 2026，实得 {model.order.date}"
    )


@pytest.mark.parametrize(
    "tz_name,expected",
    [
        ("Asia/Shanghai", "27 July 2026"),   # UTC+8
        ("Asia/Tokyo", "27 July 2026"),      # UTC+9
        ("Europe/London", "27 July 2026"),   # 夏令时 UTC+1
        ("America/New_York", "26 July 2026"),  # UTC-4，仍在 26 日
    ],
)
def test_timezone_actually_drives_the_date(frozen_utc_host, tz_name, expected):
    """不同时区得出不同日期 —— 证明配置是真的生效，不是被忽略。"""
    model = _assemble(_config_with_tz(tz_name))
    assert model.order.date == expected


def test_date_format_config_still_respected(frozen_utc_host):
    """业务时区不应影响 date_format 的输出格式。"""
    cfg = _config_with_tz("Asia/Shanghai")
    cfg.setdefault("defaults", {})["date_format"] = "%Y-%m-%d"
    model = _assemble(cfg)
    assert model.order.date == "2026-07-27"


# ─────────────────────────────────────────────────────────────
# 配置文档与向导：新配置项必须可被发现
# ─────────────────────────────────────────────────────────────


def test_builtin_config_documents_business_timezone():
    """内置 config.yaml（用户默认拿到的）必须写出该键并说明为什么。

    一个只有代码知道、配置模板里不出现的选项，等于不存在 —— 用户不会去猜。
    """
    from trade_pipeline.paths import config_path

    cfg_file = config_path()
    text = cfg_file.read_text(encoding="utf-8")
    assert "business_timezone" in text, "内置 config.yaml 缺少 business_timezone 说明"

    data = yaml.safe_load(text)
    assert "business_timezone" in data.get("defaults", {}), "该键应出现在 defaults 段下"

    # 说明必须讲清"不填会怎样"，否则用户没有理由去填
    idx = text.index("business_timezone")
    context = text[max(0, idx - 500):idx]
    assert "前一天" in context or "UTC" in context, (
        "该键附近应说明不配置的后果（UTC 服务器上会印错一天）"
    )


def test_init_wizard_writes_business_timezone(monkeypatch, tmp_path):
    """初始化向导必须把这个键写进生成的配置。"""
    import builtins
    import trade_pipeline.cli.init_wizard as wizard

    # run_init 读的是模块级常量 CONFIG_PATH（不是 _get_config_path 那个兼容 shim）
    target = tmp_path / "config" / "config.yaml"
    monkeypatch.setattr(wizard, "CONFIG_PATH", target)
    assert not target.exists(), "本用例假定目标配置不存在，以便跳过覆盖确认"

    answers = [
        "", "", "Qingdao", "Zhang San", "z@example.com", "+86-532-99999",
        "Bank of Test", "TESTCNBJXXX", "1234567890",
        "1", "1", "QINGDAO,CHINA",
        "America/New_York",          # business_timezone —— 刻意选个非常用值，证明它被采纳
        "30% TT", "45 days", "10 days",
        "1", "n",
    ]
    queue = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(queue, ""))

    wizard.run_init()

    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["defaults"]["business_timezone"] == "America/New_York", (
        "向导应把用户填写的业务时区写进 defaults.business_timezone"
    )
