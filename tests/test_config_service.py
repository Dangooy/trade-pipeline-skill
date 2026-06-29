"""
tests/test_config_service.py — ConfigService（v1.2.0 ConfigTab 底层）单元测试

测试覆盖：
- ID 生成（make_entity_id / ensure_unique_id）
- 字段校验（validate_seller / validate_buyer）
- 读 / 写 / 备份 / 原子替换
- seller / buyer 的 add / update / delete
- 字段隔离（CRUD 不影响 packing / pl_profiles / cache 等非身份段）
"""
from pathlib import Path

import pytest
import yaml

from trade_pipeline.config_service import (
    ConfigService,
    empty_buyer,
    empty_seller,
    ensure_unique_id,
    make_entity_id,
    validate_buyer,
    validate_seller,
)


# ── ID 生成 ──
class TestMakeEntityId:
    def test_basic(self):
        assert make_entity_id("Global Fasteners LLC") == "global_fasteners"

    def test_strip_punctuation(self):
        assert make_entity_id("ACME EXPORT CO., LTD.") == "acme_export"

    def test_russian_company(self):
        assert make_entity_id('OOO "Metiz Trading"') == "metiz_trading"

    def test_empty(self):
        assert make_entity_id("") == "entity"
        assert make_entity_id("   ") == "entity"

    def test_only_stopwords(self):
        # 全是停用词时回退到 fallback
        assert make_entity_id("Co Ltd Inc", fallback="seller") == "seller"

    def test_gmbh(self):
        assert make_entity_id("EuroFix GmbH") == "eurofix"


class TestEnsureUniqueId:
    def test_no_collision(self):
        assert ensure_unique_id("acme", set()) == "acme"
        assert ensure_unique_id("acme", {"other"}) == "acme"

    def test_collision_appends_2(self):
        assert ensure_unique_id("acme", {"acme"}) == "acme_2"

    def test_multi_collision(self):
        assert ensure_unique_id("acme", {"acme", "acme_2", "acme_3"}) == "acme_4"


# ── 校验 ──
class TestValidateSeller:
    def test_valid_minimal(self):
        data = empty_seller()
        data["name_en"] = "ACME Co"
        assert validate_seller(data) == []

    def test_missing_name_en(self):
        data = empty_seller()
        errors = validate_seller(data)
        assert any("英文" in e for e in errors)

    def test_bad_email(self):
        data = empty_seller()
        data["name_en"] = "ACME"
        data["email"] = "not-an-email"
        errors = validate_seller(data)
        assert any("邮箱" in e for e in errors)

    def test_empty_email_ok(self):
        data = empty_seller()
        data["name_en"] = "ACME"
        data["email"] = ""
        assert validate_seller(data) == []

    def test_bad_swift_length(self):
        data = empty_seller()
        data["name_en"] = "ACME"
        data["bank"]["swift"] = "ABCDE"
        errors = validate_seller(data)
        assert any("SWIFT" in e for e in errors)

    def test_swift_8_or_11(self):
        for sw in ("ABCDEFGH", "ABCDEFGHIJK"):
            data = empty_seller()
            data["name_en"] = "ACME"
            data["bank"]["swift"] = sw
            assert validate_seller(data) == []


class TestValidateBuyer:
    def test_valid_minimal(self):
        data = empty_buyer()
        data["name_en"] = "Global Fasteners"
        assert validate_buyer(data) == []

    def test_missing_name_en(self):
        assert any("英文" in e for e in validate_buyer(empty_buyer()))


# ── ConfigService ──
@pytest.fixture
def cfg_path(tmp_path) -> Path:
    p = tmp_path / "config.yaml"
    sample = {
        "sellers": {
            "acme": {
                "name_cn": "示例",
                "name_en": "ACME Co",
                "bank": {"name": "Bank A", "swift": "ABCDEFGH"},
            }
        },
        "buyers": {
            "gf": {"name_en": "Global Fasteners"},
        },
        "packing": {"carton_weight_kg": 25, "cartons_per_pallet": 36},
        "pl_profiles": {"default": {"pl_config": "standard"}},
        "cache": {"enabled": True},
    }
    p.write_text(yaml.dump(sample, allow_unicode=True), encoding="utf-8")
    return p


class TestEmptySectionBoundary:
    """回归 Codex review P1#1：sellers: {} 状态下 add_seller 必须能落盘。"""

    def test_add_seller_to_empty_dict(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("sellers: {}\nbuyers: {}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        new = empty_seller()
        new["name_en"] = "First Co"
        svc.add_seller("first", new)
        svc.save()
        reloaded = ConfigService(p)
        reloaded.load()
        assert "first" in reloaded.sellers(), \
            "sellers: {} 状态下 add 必须落盘（P1#1 回归）"

    def test_add_buyer_to_empty_dict(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("sellers: {}\nbuyers: {}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        new = empty_buyer()
        new["name_en"] = "First Buyer"
        svc.add_buyer("first", new)
        svc.save()
        reloaded = ConfigService(p)
        reloaded.load()
        assert "first" in reloaded.buyers(), \
            "buyers: {} 状态下 add 必须落盘（P1#1 回归）"

    def test_add_seller_when_section_missing(self, tmp_path):
        """yaml 完全没有 sellers 段时也能新增。"""
        p = tmp_path / "config.yaml"
        p.write_text("packing:\n  carton_weight_kg: 25\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        new = empty_seller()
        new["name_en"] = "ACME"
        svc.add_seller("acme", new)
        svc.save()
        reloaded = ConfigService(p)
        reloaded.load()
        assert "acme" in reloaded.sellers()
        # 非身份段也应保留
        assert reloaded.data.get("packing", {}).get("carton_weight_kg") == 25

    def test_sellers_returns_same_object(self, tmp_path):
        """sellers() 必须返回 _data 里的真实 dict，不是悬空副本。"""
        p = tmp_path / "config.yaml"
        p.write_text("sellers: {}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        d = svc.sellers()
        assert d is svc._data["sellers"], "sellers() 必须返回 _data 内的 dict"


class TestConfigServiceLoadSave:
    def test_load(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        assert "acme" in svc.sellers()
        assert "gf" in svc.buyers()

    def test_save_creates_backup(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        svc.save()
        backup = cfg_path.with_suffix(".yaml.bak")
        assert backup.exists(), "save() 必须生成 .bak"

    def test_save_atomic_no_tmp_left(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        svc.save()
        tmp = cfg_path.with_suffix(".yaml.tmp")
        assert not tmp.exists(), "save() 后不应残留 .tmp"

    def test_load_missing_file(self, tmp_path):
        svc = ConfigService(tmp_path / "nonexistent.yaml")
        svc.load()
        assert svc.data == {}

    def test_save_preserves_non_identity_sections(self, cfg_path):
        """CRUD 之后 packing / pl_profiles / cache 段必须原样保留。"""
        svc = ConfigService(cfg_path)
        svc.load()
        svc.delete_seller("acme")
        svc.add_buyer("new_buyer", empty_buyer())
        svc.save()

        # 读回来验证非身份段未动
        reloaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert reloaded["packing"]["carton_weight_kg"] == 25
        assert reloaded["packing"]["cartons_per_pallet"] == 36
        assert reloaded["pl_profiles"]["default"]["pl_config"] == "standard"
        assert reloaded["cache"]["enabled"] is True


class TestSellerCRUD:
    def test_add_seller(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        new = empty_seller()
        new["name_en"] = "New Co"
        svc.add_seller("new_co", new)
        svc.save()
        assert "new_co" in ConfigService(cfg_path).load()["sellers"]

    def test_update_seller(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        updated = dict(svc.sellers()["acme"])
        updated["tel"] = "+86 138 0000"
        svc.update_seller("acme", updated)
        svc.save()
        reloaded = ConfigService(cfg_path)
        reloaded.load()
        assert reloaded.sellers()["acme"]["tel"] == "+86 138 0000"

    def test_update_seller_missing(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        with pytest.raises(KeyError):
            svc.update_seller("ghost", empty_seller())

    def test_delete_seller(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        svc.delete_seller("acme")
        svc.save()
        reloaded = ConfigService(cfg_path)
        reloaded.load()
        assert "acme" not in reloaded.sellers()

    def test_delete_seller_missing_is_noop(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        svc.delete_seller("ghost")  # 不抛错
        svc.save()

    def test_delete_last_seller_allowed(self, cfg_path):
        """产品方向：允许删到 0 个卖家。"""
        svc = ConfigService(cfg_path)
        svc.load()
        svc.delete_seller("acme")
        svc.save()
        assert ConfigService(cfg_path).load().get("sellers", {}) == {}


class TestBuyerCRUD:
    def test_add_buyer(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        new = empty_buyer()
        new["name_en"] = "New Buyer Ltd"
        svc.add_buyer("new_buyer", new)
        svc.save()
        assert "new_buyer" in ConfigService(cfg_path).load()["buyers"]

    def test_delete_buyer(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        svc.delete_buyer("gf")
        svc.save()
        assert "gf" not in ConfigService(cfg_path).load().get("buyers", {})


class TestSellerReferences:
    """回归 Codex review P1#2：检测 format_defaults 中对 seller 的引用。"""

    @pytest.fixture
    def cfg_with_refs(self, tmp_path) -> Path:
        p = tmp_path / "config.yaml"
        sample = {
            "sellers": {
                "acme": {"name_en": "ACME"},
                "delta": {"name_en": "Delta"},
            },
            "buyers": {"gf": {"name_en": "GF"}},
            "format_defaults": {
                "standard": {"seller_id": "acme", "currency": "CNY"},
                "standard_usd": {"seller_id": "acme", "currency": "USD"},
                "washers_mar": {"seller_id": "delta", "currency": "USD"},
            },
        }
        p.write_text(yaml.dump(sample, allow_unicode=True), encoding="utf-8")
        return p

    def test_find_references_for_referenced_seller(self, cfg_with_refs):
        svc = ConfigService(cfg_with_refs)
        svc.load()
        refs = svc.find_seller_references("acme")
        assert set(refs) == {"standard", "standard_usd"}

    def test_find_references_for_unreferenced_seller(self, cfg_with_refs):
        svc = ConfigService(cfg_with_refs)
        svc.load()
        svc.add_seller("orphan", empty_seller())
        assert svc.find_seller_references("orphan") == []

    def test_clear_format_references(self, cfg_with_refs):
        svc = ConfigService(cfg_with_refs)
        svc.load()
        svc.clear_format_references(["standard", "standard_usd"])
        svc.save()
        reloaded = ConfigService(cfg_with_refs)
        reloaded.load()
        fmt = reloaded.data.get("format_defaults", {})
        assert "standard" not in fmt
        assert "standard_usd" not in fmt
        # 未指定的 washers_mar 保留
        assert "washers_mar" in fmt

    def test_find_references_no_format_defaults_section(self, tmp_path):
        """yaml 没 format_defaults 段时返回空列表（不抛错）。"""
        p = tmp_path / "config.yaml"
        p.write_text("sellers:\n  acme: {name_en: A}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        assert svc.find_seller_references("acme") == []


class TestUniqueIdGeneration:
    def test_unique_seller_id_no_collision(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        assert svc.make_unique_seller_id("New Co") == "new"  # "co" is stopword

    def test_unique_seller_id_with_collision(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        assert svc.make_unique_seller_id("ACME Co") == "acme_2"

    def test_unique_buyer_id(self, cfg_path):
        svc = ConfigService(cfg_path)
        svc.load()
        # gf 占了名字 "global" 吗？不——key 是 "gf"，所以 Global Fasteners 不冲突
        assert svc.make_unique_buyer_id("Global Fasteners") == "global_fasteners"


class TestMergeDemo:
    """merge_demo：首启「加载示例数据」的增量合并逻辑。"""

    DEMO = {
        "sellers": {
            "acme_export": {"name_en": "ACME EXPORT", "email": "demo@acme.example.com"},
            "delta_mfg": {"name_en": "DELTA MFG"},
        },
        "buyers": {
            "global_fasteners": {"name_en": "Global Fasteners LLC"},
            "metiz_trading": {"name_en": 'OOO "Metiz Trading"'},
        },
    }

    def test_merge_demo_adds_new(self, tmp_path):
        """空 config 合并 demo：所有实体都被加入并落盘。"""
        p = tmp_path / "config.yaml"
        p.write_text("sellers: {}\nbuyers: {}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        stats = svc.merge_demo(self.DEMO)

        assert set(stats["sellers_added"]) == {"acme_export", "delta_mfg"}
        assert set(stats["buyers_added"]) == {"global_fasteners", "metiz_trading"}
        assert stats["skipped"] == []
        # 落盘后能读回
        reloaded = ConfigService(p)
        reloaded.load()
        assert "acme_export" in reloaded.sellers()
        assert "metiz_trading" in reloaded.buyers()

    def test_merge_demo_skips_existing(self, tmp_path):
        """关键用例：已存在的同名实体不被 demo 覆盖，用户原值保留。"""
        p = tmp_path / "config.yaml"
        svc = ConfigService(p)
        svc.load()
        # 用户已有一个同 id 但值不同的卖家
        svc.add_seller("acme_export", {"name_en": "用户自己的 ACME", "email": "mine@me.com"})
        svc.save()

        stats = svc.merge_demo(self.DEMO)

        # acme_export 被跳过、delta_mfg 被新增
        assert "seller:acme_export" in stats["skipped"]
        assert stats["sellers_added"] == ["delta_mfg"]
        # 用户原值完整保留，没被 demo 的 ACME EXPORT 覆盖
        reloaded = ConfigService(p)
        reloaded.load()
        assert reloaded.sellers()["acme_export"]["name_en"] == "用户自己的 ACME"
        assert reloaded.sellers()["acme_export"]["email"] == "mine@me.com"

    def test_merge_demo_saves_and_backups(self, tmp_path):
        """有新增时触发 save()：生成 .bak 备份；全跳过时不写盘。"""
        p = tmp_path / "config.yaml"
        p.write_text("sellers: {}\nbuyers: {}\n", encoding="utf-8")
        svc = ConfigService(p)
        svc.load()
        svc.merge_demo(self.DEMO)
        assert p.with_suffix(".yaml.bak").exists()

        # 第二次合并：全部已存在 → 全跳过 → 不应有任何新增
        svc2 = ConfigService(p)
        svc2.load()
        stats2 = svc2.merge_demo(self.DEMO)
        assert stats2["sellers_added"] == []
        assert stats2["buyers_added"] == []
        assert len(stats2["skipped"]) == 4
