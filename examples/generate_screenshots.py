"""Generate sample output files for screenshots."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from trade_pipeline.models.order_model import OrderModel, OrderRefs, OrderInfo, OrderItem, DerivedData, OrderMeta
from trade_pipeline.understanding.assembler import resolve_entities
from trade_pipeline.writers.quote_writer import write_quotation_with_uuid
from trade_pipeline.writers.pi_writer import PIWriter
from trade_pipeline.writers.ci_writer import CIWriter
from trade_pipeline.writers.pl_writer_lite import PLWriterLite

config_path = Path(__file__).resolve().parent.parent / "trade_pipeline" / "config" / "config.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

items = [
    OrderItem(no=1, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 933",
              description_raw="HEX HEAD BOLT DIN 933 M8x25 ZP", description="HEX HEAD BOLT DIN 933 M8x25 ZP",
              quantity=50000, unit="pcs", weight_kg=290.0, barcode="GF-HB-001", kg_mpcs=5.80,
              group_key="DIN 933 — HEX HEAD BOLT — ZP", unit_price=28.50),
    OrderItem(no=2, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 933",
              description_raw="HEX HEAD BOLT DIN 933 M10x30 ZP", description="HEX HEAD BOLT DIN 933 M10x30 ZP",
              quantity=30000, unit="pcs", weight_kg=336.0, barcode="GF-HB-002", kg_mpcs=11.20,
              group_key="DIN 933 — HEX HEAD BOLT — ZP", unit_price=45.00),
    OrderItem(no=3, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 933",
              description_raw="HEX HEAD BOLT DIN 933 M12x40 ZP", description="HEX HEAD BOLT DIN 933 M12x40 ZP",
              quantity=20000, unit="pcs", weight_kg=410.0, barcode="GF-HB-003", kg_mpcs=20.50,
              group_key="DIN 933 — HEX HEAD BOLT — ZP", unit_price=72.00),
    OrderItem(no=4, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 934",
              description_raw="HEX NUT DIN 934 M8 ZP", description="HEX NUT DIN 934 M8 ZP",
              quantity=100000, unit="pcs", weight_kg=280.0, barcode="GF-HN-001", kg_mpcs=2.80,
              group_key="DIN 934 — HEX NUT — ZP", unit_price=12.00),
    OrderItem(no=5, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 934",
              description_raw="HEX NUT DIN 934 M10 ZP", description="HEX NUT DIN 934 M10 ZP",
              quantity=80000, unit="pcs", weight_kg=448.0, barcode="GF-HN-002", kg_mpcs=5.60,
              group_key="DIN 934 — HEX NUT — ZP", unit_price=22.00),
    OrderItem(no=6, item_uuid=OrderItem.generate_uuid(), part_no=None, standard="DIN 125",
              description_raw="FLAT WASHER DIN 125 M8 ZP", description="FLAT WASHER DIN 125 M8 ZP",
              quantity=200000, unit="pcs", weight_kg=300.0, barcode="GF-FW-001", kg_mpcs=1.50,
              group_key="DIN 125 — FLAT WASHER — ZP", unit_price=5.50),
]

model = OrderModel(
    refs=OrderRefs(seller_id="acme_export", buyer_id="global_fasteners", terms_id="standard_cny"),
    order=OrderInfo(order_no="2601", format="standard", quote_no="QT-2601", pi_number="PI-2601",
                    ci_number="CI-2601", date="19 May 2026", currency="CNY", price_unit="CNY/MPCS"),
    items=items,
    derived=DerivedData(total_items=6, total_qty=480000, has_weight=True,
                        port_of_loading="QINGDAO,CHINA"),
    meta=OrderMeta(source_files=["sample_inquiry.xlsx"], created_at="2026-05-19", parser_model="rules"),
)

model = resolve_entities(model, config)

out_dir = Path(__file__).resolve().parent / "sample_output"
out_dir.mkdir(exist_ok=True)

quote_info = write_quotation_with_uuid(
    items, str(out_dir / "2601_quotation.xlsx"), "2601",
    has_weight=True, currency="CNY", price_unit="CNY/MPCS",
    seller=model.resolved.seller if model.resolved else {},
    buyer=model.resolved.buyer if model.resolved else {},
    terms=model.resolved.terms if model.resolved else {},
    date=model.order.date,
)
print(f"Quotation: {quote_info['items']} items")

pi_writer = PIWriter(model, config)
pi_info = pi_writer.write(str(out_dir / "2601_pi.xlsx"))
print(f"PI: {pi_info['items']} items, {pi_info['pi_number']}")

ci_writer = CIWriter(model, config)
ci_info = ci_writer.write(str(out_dir / "2601_ci.xlsx"))
print(f"CI: {ci_info['items']} items, {ci_info['ci_number']}")

pl_writer = PLWriterLite(model, config)
pl_info = pl_writer.write(str(out_dir / "2601_pl.xlsx"))
print(f"PL: {pl_info['items']} items, {pl_info['total_pallets']} pallets")

print(f"\nSample output files generated in: {out_dir}")
