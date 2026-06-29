# CLAUDE.md — Instructions for AI Agents

## Quick Start

```bash
pip install -e .
python -m trade_pipeline --input examples/sample_inquiry.xlsx --order TEST01 --buyer global_fasteners
```

Output goes to `output/TEST01/`. Steps 1–7 generate: rfq.json, model.json, quotation.xlsx, pi.xlsx, ci.xlsx. Step 8 (PL) is optional and requires the separate `pl-gen` package.

## Project Structure

```
trade_pipeline/
├── extractors/     # Step 1: Excel → ExtractedDocument
├── understanding/  # Steps 2-4: parse → canonicalize → assemble OrderModel
├── models/         # OrderModel dataclass (single source of truth)
├── writers/        # Steps 5-8: generate Excel documents from OrderModel
├── validation/     # review.json mechanism for human-in-the-loop
├── adapters/       # PL config resolution
├── legacy/         # Bridge to external pl-gen (optional)
├── pipeline/       # Main orchestrator (main.py) + price updater
└── config/         # config.yaml (sellers, buyers, terms, formats)
```

## Key Rules

- **All Writers read from OrderModel only** — never re-parse Excel in a Writer
- **Buyer match failure = hard block** — generates review.json, pipeline stops
- **UUID anchoring** — quotation has hidden UUID column; price write-back uses UUID, not row numbers
- **Config-driven** — change `config/config.yaml` to add sellers, buyers, terms, formats

## What You Can Modify

| File | Safe to edit | Notes |
|------|-------------|-------|
| `config/config.yaml` | Yes | Add/change sellers, buyers, terms, pricing formats |
| `understanding/canonicalizer.py` | Yes | Add product name translations, standard normalization rules |
| `understanding/llm_parser.py` | Yes | Add column header mappings, format detection rules |
| `writers/*.py` | Carefully | Layout changes are safe; don't bypass OrderModel |
| `models/order_model.py` | Carefully | Adding fields is safe; renaming/removing breaks serialization |

## Running the Sample

```bash
# Generate sample output (steps 1-7)
python -m trade_pipeline --input examples/sample_inquiry.xlsx --order DEMO01 --buyer global_fasteners

# Verify output
ls output/DEMO01/
# Expected: DEMO01_rfq.json, DEMO01_model.json, DEMO01_quotation.xlsx, DEMO01_pi.xlsx, DEMO01_ci.xlsx

# Price write-back (after filling prices in quotation)
python -m trade_pipeline --price-update output/DEMO01/DEMO01_quotation.xlsx --model output/DEMO01/DEMO01_model.json
```

## PL Dual Mode

Step 8 (Packing List) has two modes:
- **Lite mode** (default in this repo): Built-in `pl_writer_lite.py` with standard packing rules (25 kg/carton, 36 cartons/pallet). Fully functional.
- **Full mode**: Connects to external private `pl-gen` engine with customer-specific templates and algorithms. Auto-detected when `pl-gen` directory exists alongside this repo.

Both modes produce a complete packing list Excel. The pipeline auto-selects the available mode.
