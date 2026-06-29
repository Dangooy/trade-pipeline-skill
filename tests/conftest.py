"""Shared test fixtures for trade_pipeline tests."""

import pytest
import yaml

from trade_pipeline.models.order_model import (
    OrderModel, OrderRefs, OrderInfo, OrderItem, DerivedData,
    ResolvedEntities, OrderMeta,
)


SAMPLE_CONFIG = {
    "buyers": {
        "global_fasteners": {
            "name_en": "Global Fasteners LLC",
            "name_ru": None,
            "legal_names": ["Global Fasteners LLC", "Global Fasteners Limited Liability Company"],
            "aliases": ["GF", "Global Fasteners"],
            "address": "Chicago, IL, USA",
            "contact": "John Smith",
            "email": "john@globalfasteners.example.com",
        },
        "metiz_trading": {
            "name_en": 'OOO "Metiz Trading"',
            "name_ru": 'ООО "Метиз Трейдинг"',
            "legal_names": ['OOO "Metiz Trading"', 'ООО "Метиз Трейдинг"'],
            "aliases": ["Metiz Trading", "Метиз Трейдинг"],
            "address": "Moscow, Russia",
        },
    },
    "sellers": {
        "acme_export": {
            "name_cn": "示例出口公司",
            "name_en": "ACME EXPORT CO., LTD",
            "address": "123 Export Road, Qingdao, China",
            "contact": "Zhang Wei",
            "email": "zhang@acme-export.example.com",
            "tel": "+86-532-12345678",
            "bank": {
                "name": "Bank of China Qingdao",
                "swift": "BKCHCNBJXXX",
                "account_no": "1234567890",
            },
        },
    },
    "format_defaults": {
        "standard": {
            "seller_id": "acme_export",
            "currency": "USD",
            "price_unit": "USD/PC",
            "terms_id": "default_usd",
        },
    },
    "terms_templates": {
        "default_usd": {
            "payment": "30% T/T deposit; 70% before shipment",
            "delivery": "FOB QINGDAO, CHINA, Incoterms 2020.",
            "lead_time": "45-60 days after deposit",
            "validity": "10 days",
            "packing": "Standard export packaging: 25 kg cartons, Euro pallets.",
            "quality": "100% inspection before shipment.",
        },
    },
    "defaults": {
        "port_of_loading": "QINGDAO, CHINA",
        "pi_number_pattern": "PI-{order_no}",
        "ci_number_pattern": "CI-{order_no}",
        "quote_no_pattern": "QT-{order_no}",
    },
    "packing": {
        "carton_weight_kg": 25,
        "pallet_self_weight_kg": 28,
        "cartons_per_pallet": 36,
    },
}


@pytest.fixture(autouse=True)
def inject_test_config(tmp_path, monkeypatch):
    """把 pipeline.main 读取的 config 重定向到 SAMPLE_CONFIG 临时文件。

    背景：v1.2.0 起模板 config.yaml 的 sellers/buyers 清空（首启体验），
    真实 config 不再含 global_fasteners 等实体。但 e2e/cli/precheck 测试通过
    pipeline.main.run(buyer_id="global_fasteners") 走 main.config_path() 读真实
    config，清空后这些测试会因实体缺失而失败。

    本 fixture 用 SAMPLE_CONFIG（含 acme_export/global_fasteners/metiz_trading）
    dump 出临时 config.yaml，monkeypatch main.config_path 指向它，让那些测试
    在"有实体"的环境里跑，断言保持不变。

    patch 目标确认：main.py 在模块顶部 `from ...paths import config_path`，
    load_config()/run()/run_price_update() 三处都调模块级 config_path，
    patch 一处全覆盖（与 test_precheck_cli.py 既有的局部 patch 同目标）。

    autouse 安全性：已隔离的测试（直接构造 OrderModel、自建 tmp config、用
    inline SAMPLE_CONFIG 的）不引用 main.config_path，patch 它们不碰的符号 = 零副作用。
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(SAMPLE_CONFIG, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("trade_pipeline.pipeline.main.config_path", lambda: str(cfg))
    return cfg


def make_model(with_prices: bool = False, with_weights: bool = True) -> OrderModel:
    """Create a test OrderModel with configurable price/weight data."""
    return OrderModel(
        refs=OrderRefs(seller_id="acme_export", buyer_id="global_fasteners", terms_id="default_usd"),
        order=OrderInfo(
            order_no="TEST01", format="standard", quote_no="QT-TEST01",
            pi_number="PI-TEST01", ci_number="CI-TEST01", date="19 May 2026",
            currency="USD", price_unit="USD/PC",
        ),
        items=[
            OrderItem(
                no=1, item_uuid="abc123def456", part_no=None, standard="DIN 933",
                description_raw="HEX BOLT M8x25", description="HEX HEAD BOLT DIN 933 M8x25 ZP",
                quantity=50000, unit="pcs",
                weight_kg=290.0 if with_weights else None,
                barcode="GF-001",
                unit_price=28.50 if with_prices else None,
                kg_mpcs=5.8 if with_weights else None,
            ),
            OrderItem(
                no=2, item_uuid="xyz789ghi012", part_no=None, standard="DIN 934",
                description_raw="HEX NUT M8", description="HEX NUT DIN 934 M8 ZP",
                quantity=100000, unit="pcs",
                weight_kg=280.0 if with_weights else None,
                barcode="GF-002",
                unit_price=12.00 if with_prices else None,
                kg_mpcs=2.8 if with_weights else None,
            ),
        ],
        derived=DerivedData(total_items=2, total_qty=150000, has_weight=with_weights),
        meta=OrderMeta(source_files=["test.xlsx"], parser_model="rules"),
    )


def make_resolved_model(with_prices: bool = False, with_weights: bool = True) -> OrderModel:
    """Create a test OrderModel with resolved entities (seller/buyer/terms filled)."""
    model = make_model(with_prices=with_prices, with_weights=with_weights)
    model.resolved = ResolvedEntities(
        seller=SAMPLE_CONFIG["sellers"]["acme_export"],
        buyer=SAMPLE_CONFIG["buyers"]["global_fasteners"],
        terms=SAMPLE_CONFIG["terms_templates"]["default_usd"],
        bank=SAMPLE_CONFIG["sellers"]["acme_export"]["bank"],
    )
    return model
