"""init_wizard tests — pure-function + mocked input() flows.

Strategy:
- 纯函数 (_make_seller_id / _make_buyer_id) 直接断言
- _ask / _ask_choice 用 monkeypatch.setattr(builtins, "input", ...) 注入
- run_init 用预制的输入序列模拟用户交互，并把 CONFIG_PATH 重定向到 tmp_path

Trade-pipeline 的 init wizard 是 cold-start 入口，覆盖率从 0% 拉起来收益高。
"""
import builtins

import pytest
import yaml

from trade_pipeline.cli import init_wizard
from trade_pipeline.cli.init_wizard import (
    _make_seller_id,
    _make_buyer_id,
    _ask,
    _ask_choice,
    run_init,
    add_buyer_interactive,
    TRADE_TERMS_OPTIONS,
    CURRENCY_OPTIONS,
)


# ── 纯函数 ────────────────────────────────────────────────────────


def test_make_seller_id_drops_corporate_suffixes():
    """seller_id 应该剥离 Co/Ltd/Inc 等公司后缀。"""
    assert _make_seller_id("ACME EXPORT CO., LTD") == "acme_export"
    assert _make_seller_id("Foo Bar Inc.") == "foo_bar"
    assert _make_seller_id("Single") == "single"


def test_make_seller_id_fallback_when_only_suffixes():
    """全是后缀词时回退到 my_company。"""
    assert _make_seller_id("Co Ltd Inc") == "my_company"


def test_make_buyer_id_handles_quotes_and_russian():
    """buyer_id 应该去除引号且支持俄文 ООО。"""
    assert _make_buyer_id('OOO "Metiz Trading"') == "metiz_trading"
    assert _make_buyer_id("Global Fasteners LLC") == "global_fasteners"


def test_make_buyer_id_fallback():
    """全是后缀时回退到 buyer_1。"""
    assert _make_buyer_id("OOO LLC") == "buyer_1"


# ── 交互辅助函数 ─────────────────────────────────────────────────


def test_ask_returns_user_input_when_provided(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "  hello  ")
    assert _ask("Q", default="x") == "hello"


def test_ask_returns_default_when_blank(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert _ask("Q", default="fallback") == "fallback"


def test_ask_choice_returns_valid_selection(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "2")
    result = _ask_choice("Pick:", TRADE_TERMS_OPTIONS, default="1")
    assert result == "2"


def test_ask_choice_falls_back_to_default_on_invalid(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "99")
    result = _ask_choice("Pick:", CURRENCY_OPTIONS, default="1")
    assert result == "1"


# ── run_init 完整流程 ─────────────────────────────────────────────


class _InputQueue:
    """喂给 builtins.input 的输入队列；如用尽返回空串触发 default。"""
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, prompt: str = "") -> str:
        self.calls += 1
        if self.answers:
            return self.answers.pop(0)
        return ""


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """把 init_wizard.CONFIG_PATH 重定向到临时目录，避免污染真实配置。"""
    fake_path = tmp_path / "config" / "config.yaml"
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", fake_path)
    return fake_path


def test_run_init_minimal_flow_writes_config(monkeypatch, isolated_config):
    """跑最小流程：USD/FOB/无 buyer，应该写出有效 yaml。"""
    # 输入顺序对应 run_init 里 _ask + input 的调用顺序
    # seller_name_cn, seller_name_en, seller_id 不需要(自动推导),
    # address, contact, email, tel,
    # bank_name, bank_swift, bank_account,
    # terms_choice("1"=FOB), currency_choice("1"=USD), port, payment, lead, validity,
    # pu_choice("1"=USD/PC), add_buyer("n")
    answers = [
        "",                        # name_cn (default 空)
        "TEST EXPORT CO., LTD",    # name_en
        "Qingdao",                 # address
        "Zhang San",               # contact
        "zhang@test.com",          # email
        "+86-532-99999",           # tel
        "Bank of Test",            # bank_name
        "TESTCNBJXXX",             # bank_swift
        "1234567890",              # bank_account
        "1",                       # terms (FOB)
        "1",                       # currency (USD)
        "QINGDAO,CHINA",           # port
        "30% TT",                  # payment
        "45 days",                 # lead_time
        "10 days",                 # validity
        "1",                       # pu_choice (USD/PC)
        "n",                       # add_buyer: no
    ]
    q = _InputQueue(answers)
    monkeypatch.setattr(builtins, "input", q)

    run_init()

    assert isolated_config.exists(), "config.yaml 应写出"
    data = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert "sellers" in data
    assert "test_export" in data["sellers"]
    assert data["sellers"]["test_export"]["name_en"] == "TEST EXPORT CO., LTD"
    assert data["format_defaults"]["standard"]["currency"] == "USD"
    assert data["format_defaults"]["standard"]["price_unit"] == "USD/PC"
    assert data["buyers"] == {}, "选 n 时不应创建 buyer"


def test_run_init_with_buyer_flow_writes_buyer(monkeypatch, isolated_config):
    """带 buyer 的流程，buyers 段应该有内容。"""
    answers = [
        "",                        # name_cn
        "DJ EXPORT LIMITED",       # name_en
        "Wuxi",                    # address
        "Ethan",                   # contact
        "ethan@dj.com",            # email
        "",                        # tel
        "",                        # bank_name
        "",                        # bank_swift
        "",                        # bank_account
        "2",                       # terms (CIF)
        "1",                       # currency (USD)
        "SHANGHAI,CHINA",          # port
        "",                        # payment (default)
        "",                        # lead_time (default)
        "",                        # validity (default)
        "1",                       # pu_choice USD/PC
        "y",                       # add_buyer yes
        "Global Test LLC",         # buyer_name
        "Chicago",                 # buyer_address
        "John",                    # buyer_contact
        "john@test.com",           # buyer_email
    ]
    q = _InputQueue(answers)
    monkeypatch.setattr(builtins, "input", q)

    run_init()

    data = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert "global_test" in data["buyers"]
    assert data["buyers"]["global_test"]["name_en"] == "Global Test LLC"


def test_run_init_cny_uses_mpcs_pricing(monkeypatch, isolated_config):
    """选 CNY 时 price_unit 应自动是 CNY/MPCS（无需 pu_choice）。"""
    answers = [
        "",                        # name_cn
        "CN COMPANY",              # name_en
        "Beijing",                 # address
        "",                        # contact
        "",                        # email
        "",                        # tel
        "",                        # bank_name
        "",                        # bank_swift
        "",                        # bank_account
        "1",                       # terms (FOB)
        "2",                       # currency (CNY) → 跳过 pu_choice
        "BEIJING,CHINA",           # port
        "",                        # payment
        "",                        # lead_time
        "",                        # validity
        "n",                       # add_buyer no
    ]
    q = _InputQueue(answers)
    monkeypatch.setattr(builtins, "input", q)

    run_init()

    data = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert data["format_defaults"]["standard"]["price_unit"] == "CNY/MPCS"


def test_run_init_cancel_when_config_exists(monkeypatch, isolated_config):
    """已有 config.yaml 时，回答非 y → 取消，不覆盖。"""
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    original_content = "preserved: true\n"
    isolated_config.write_text(original_content, encoding="utf-8")

    # 第一个 input 是 overwrite 确认；回答 N
    monkeypatch.setattr(builtins, "input", lambda prompt: "N")

    run_init()

    # 原内容应该保留
    assert isolated_config.read_text(encoding="utf-8") == original_content


# ── add_buyer_interactive ─────────────────────────────────────────


def test_add_buyer_interactive_creates_new_buyer(monkeypatch, isolated_config):
    """匹配失败时交互创建新 buyer，应写入 config + 返回 buyer_id。"""
    # 写一个空的 config 让 add_buyer 能 dump 回去
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(yaml.dump({"buyers": {}}), encoding="utf-8")

    answers = [
        "y",                       # create
        "Saturn Trading Co.",      # name_en
        "Moscow",                  # address
        "Polina",                  # contact
        "polina@saturn.example",   # email
    ]
    q = _InputQueue(answers)
    monkeypatch.setattr(builtins, "input", q)

    config = {"buyers": {}}
    buyer_id = add_buyer_interactive(config, extracted_name="Saturn")

    assert buyer_id == "saturn_trading"
    assert "saturn_trading" in config["buyers"]
    assert config["buyers"]["saturn_trading"]["name_en"] == "Saturn Trading Co."
    # 检查写回了 config 文件
    written = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert "saturn_trading" in written["buyers"]


def test_add_buyer_interactive_user_declines(monkeypatch):
    """用户回答 n → 返回 None，不动 config。"""
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")

    config = {"buyers": {}}
    result = add_buyer_interactive(config, extracted_name="Foo")

    assert result is None
    assert config["buyers"] == {}
