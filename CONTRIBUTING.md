# Contributing

## Setup

```bash
pip install -e ".[test]"
```

## Development Commands

```bash
pytest tests/ -v                    # run tests
pytest tests/ -v --cov=trade_pipeline  # with coverage
ruff check trade_pipeline/          # lint
ruff format trade_pipeline/         # format
```

## Architecture Rules

1. **All Writers read from OrderModel only** -- never re-parse Excel in a Writer
2. **Buyer match failure = hard block** -- generates `review.json`, pipeline stops
3. **UUID anchoring** -- quotation has hidden UUID column; price write-back uses UUID, not row numbers
4. **Config-driven** -- change `config/config.yaml` for sellers, buyers, terms, formats

## Adding a New Writer

1. Inherit from `BaseWriter` in `writers/base_writer.py`
2. Implement `write(output_path: str, **kwargs) -> dict`
3. Read all data from `self.model` (OrderModel) and `self.config`
4. Return a dict with at minimum `{"success": True}` and relevant metadata
5. Add the writer call in `pipeline/main.py`
6. Add a smoke test in `tests/test_writers.py`

## Adding a New Format

1. Add detection logic in `extractors/excel_extractor.py` (`detect_format()`)
2. Add parsing rules in `understanding/llm_parser.py`
3. Add format defaults in `config/config.yaml` under `format_defaults`
4. Add test cases in `tests/test_canonicalizer.py` if new normalization rules are needed

## Project Structure

```
trade_pipeline/
  extractors/     # Step 1: Excel -> ExtractedDocument
  understanding/  # Steps 2-4: parse -> canonicalize -> assemble OrderModel
  models/         # OrderModel dataclass (single source of truth)
  writers/        # Steps 5-8: generate Excel documents from OrderModel
  validation/     # review.json mechanism for human-in-the-loop
  pipeline/       # Main orchestrator + price updater
  config/         # config.yaml (sellers, buyers, terms, formats)
```
