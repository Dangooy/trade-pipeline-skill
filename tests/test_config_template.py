"""test_config_template.py — 校验首启体验的模板分离（v1.2.0 任务卡 #2）。

直接读仓库内的真实模板文件（不经 main.config_path，故不受 conftest 的
inject_test_config autouse fixture 干扰）：
  - 模板 config.yaml：sellers/buyers 已清空，但所有非身份段保留
  - examples/demo_config.yaml：5 个示例实体齐全、字段完整
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_CONFIG = REPO / "trade_pipeline" / "config" / "config.yaml"
DEMO_CONFIG = REPO / "examples" / "demo_config.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class TestTemplateConfigCleared:
    """模板 config.yaml 的 sellers/buyers 清空、非身份段保留。"""

    def test_template_exists(self):
        assert TEMPLATE_CONFIG.exists(), f"模板 config 不存在：{TEMPLATE_CONFIG}"

    def test_sellers_empty(self):
        cfg = _load(TEMPLATE_CONFIG)
        assert cfg.get("sellers") == {}, "模板 sellers 应为空 dict（首启空白）"

    def test_buyers_empty(self):
        cfg = _load(TEMPLATE_CONFIG)
        assert cfg.get("buyers") == {}, "模板 buyers 应为空 dict（首启空白）"

    def test_non_identity_sections_preserved(self):
        """非身份段必须全部保留（清空只针对 sellers/buyers）。"""
        cfg = _load(TEMPLATE_CONFIG)
        for section in (
            "format_defaults", "terms_templates", "defaults",
            "packing", "pallet_presets", "product_catalog",
            "pl_profiles", "cache", "ocr_review",
        ):
            assert section in cfg, f"非身份段 {section} 不应被清空时误删"

    def test_format_defaults_references_preserved(self):
        """悬空引用按决策原样保留（加载 demo 后自动恢复有效）。"""
        cfg = _load(TEMPLATE_CONFIG)
        fmt = cfg.get("format_defaults", {})
        # standard 的 seller_id 引用仍在（指向 demo 里的 acme_export）
        assert fmt.get("standard", {}).get("seller_id") == "acme_export"


class TestDemoConfig:
    """examples/demo_config.yaml 含全部 5 个示例实体且字段完整。"""

    def test_demo_exists(self):
        assert DEMO_CONFIG.exists(), f"demo_config 不存在：{DEMO_CONFIG}"

    def test_demo_has_all_sellers(self):
        demo = _load(DEMO_CONFIG)
        assert set(demo.get("sellers", {}).keys()) == {"acme_export", "delta_mfg"}

    def test_demo_has_all_buyers(self):
        demo = _load(DEMO_CONFIG)
        assert set(demo.get("buyers", {}).keys()) == {
            "global_fasteners", "eurofix_gmbh", "metiz_trading",
        }

    def test_demo_seller_has_bank(self):
        """acme_export 含完整 bank 段（PI/CI 出单需要）。"""
        demo = _load(DEMO_CONFIG)
        bank = demo["sellers"]["acme_export"].get("bank", {})
        assert bank.get("swift"), "acme_export 应有 SWIFT"
        assert bank.get("account_name"), "acme_export 应有账户名"

    def test_demo_buyer_has_legal_names(self):
        """买家含 legal_names（buyer_matcher 匹配需要）。"""
        demo = _load(DEMO_CONFIG)
        assert demo["buyers"]["metiz_trading"].get("legal_names"), \
            "metiz_trading 应有 legal_names"
