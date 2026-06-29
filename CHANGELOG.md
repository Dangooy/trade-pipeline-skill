# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.2] - 2026-06-13

Pre-internal-test patch. Fixes v1.2.1 regressions + adds error-log infrastructure. GUI/CI/docs only, no business logic changes.

### Added
- Error log infrastructure: `setup_logging()` writes rotating `app.log` (2MB×3) under `user_data_root()/logs`; uncaught exceptions and Qt warnings captured via `sys.excepthook` + `qInstallMessageHandler`; worker failures logged with traceback; "export logs" button on Generate/Price-Update tabs zips logs for support
- GUI offscreen smoke now runs in CI (was never gated — the cause of v1.2.0/1.2.1 stale title/Tab assertions slipping through)

### Fixed
- `verify_gui_smoke.py` stale assertions (v1.2.0 title / 2-tab) updated to v1.2.1 three-tab + tab-text check
- `PLOnlyWorker` now forwards `output_dir` to the pipeline (defensive: packing-gateway re-run would otherwise drop PL into the default folder). Note: this GenerateTab gateway path is currently unreachable (inquiry sheets have no price column → always partial_ok), so verification is a wiring unit test; PriceUpdateTab is the reachable re-run path

### Changed
- Status bar label "输出目录" → "默认输出目录"; Generate tab output field relabeled "输出根目录" with "auto-creates an order-number subfolder" hint
- Version bumped to 1.2.2

[1.2.2]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.2.2

## [1.2.1] - 2026-06-12

First-feedback patch after the v1.2.0 release. GUI-only, no business logic changes.

### Added
- Runtime window/taskbar icon: `app.setWindowIcon` now loads `app.ico` (bundled into the runtime package); Windows AppUserModelID set so the taskbar groups under its own app instead of `python.exe`
- Generate tab: custom output directory field — leave blank for the default (`output_root()/<order>`), or pick a folder; "open output folder" follows the actual directory used

### Changed
- Version bumped to 1.2.1 (metadata three places + window title + version_info)

[1.2.1]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.2.1

## [1.2.0] - 2026-06-12

Desktop GUI productization. Consolidates pre-releases v1.2.0-alpha.1 through alpha.5.

### Added
- Three-tab desktop GUI (PySide6): 生成单据 (Generate) / 价格回写 (Price Update) / 配置中心 (Config)
- ConfigTab: visual CRUD for sellers/buyers with atomic YAML write + automatic `.bak` backup
- First-run experience: blank template (`sellers`/`buyers` cleared) + "load sample data" button; demo entities moved to `examples/demo_config.yaml`, merged incrementally without overwriting existing entries
- Pre-generation check engine: 10 rules producing a Chinese report, with blocking semantics (error blocks, warning confirmable, info advisory)
- Price write-back tab: pick filled quotation → auto-pair `model.json` → run write-back → structured precheck handling → packing gateway closed loop for missing weights
- `run_price_update` structured return: `precheck_report` (`has_errors`/`has_warnings`/`errors`/`warnings`) and `packing_review_json` output for GUI gateway integration
- Offscreen GUI smoke scripts (`verify_first_run`, `verify_gui_partial_success`, `verify_price_update`, `verify_gui_smoke`)

### Changed
- `app.py` slimmed to a `QTabWidget` shell; window title bumped to v1.2.0
- GenerateTab `partial_ok` signal distinguishes "quotation generated, formal docs pending price" from real failures
- Version metadata bumped to 1.2.0 (pyproject / plugin.json / `trade_pipeline_gui.__version__`)

### Fixed
- `assembler.py` hardcoded seller fallback removed; `_assemble_model` now catches early `EntityResolutionError` instead of leaking a traceback
- Price-update error/warning distinction now driven by structured `precheck_report` (no fragile message-string matching); warning-confirm loop no longer re-runs infinitely

[1.2.0]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.2.0

## [1.1.1] - 2026-06-08

### Added
- Dependency extras split into five groups in `pyproject.toml`; trimmed core dependencies
- `.python-version` and `requirements-dev.txt` for reproducible dev setup
- Test hardening: CLI entry coverage, `init_wizard` coverage (0% → 99%), pipeline e2e cases (59 → 82 tests, coverage 57% → 63%)

### Changed
- CI ruff + coverage scope expanded to `trade_pipeline_gui/`

[1.1.1]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.1.1

## [1.1.0] - 2026-06-08

### Added
- Packing List gateway: collects per-spec weight/packing info, auto-learns into `product_catalog.yaml`
- Pallet presets (Euro / US / Asia) in config
- `PackingGatewayDialog` GUI for in-app packing info entry — full demo → generate → gateway → PL closed loop
- `--confirm-packing` flow and `--no-catalog-save` option

### Fixed
- 15 code-review fixes across the packing and write-back paths

[1.1.0]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.1.0

## [1.0.3] - 2026-06-07

### Added
- Frozen-aware path resolution (`paths.py`): dev vs PyInstaller `.exe` modes
- PySide6 single-window desktop prototype; PyInstaller folder-mode packaging
- `PackingInfoMissingError` safety net — PI/CI still emit when PL lacks weights

[1.0.3]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.0.3

## [1.0.2] - 2026-05-24

### Changed
- `run()` refactored into four step functions
- `QuoteWriter` converted to a class; Writer helper functions deduplicated
- Removed `sys.path` hack; added `plugin.json` and `CONTRIBUTING.md`

[1.0.2]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.0.2

## [1.0.1] - 2026-05-19

### Added
- Portfolio polish: dual-version README, `--quote-only` and `--price-update` PL support

[1.0.1]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.0.1

## [1.0.0] - 2026-05-19

### Added
- Complete 8-step pipeline: RFQ Excel → Quotation → PI → CI → PL
- OrderModel single source of truth architecture
- UUID-anchored price write-back mechanism (row-order-safe)
- 4-level buyer matching + review.json hard block on failure
- Dual-mode parsing (rules / Claude API LLM) with L1/L2 cache
- Three pricing models: CNY/MPCS, USD/PC, USD/TON
- PL dual mode (built-in Lite / external private pl-gen engine)
- Cold-start init wizard (CLI interactive + Claude Code AskUserQuestion skill)
- Placeholder buyer mode (`--buyer _new`)
- Interactive buyer creation on match failure (`--interactive`)
- `--confirm review.json` flow for buyer resolution
- Trilingual README (Chinese / English / Russian)
- Three design pattern documents (Gate Pattern / Output Verification / LLM Wiki Pattern)
- Sample inquiry Excel with generation script
- Output screenshots (Quotation / PI / CI)
- Claude Code skills: trade-pipeline-init, trade-pipeline-run
- CLAUDE.md for AI agent instructions
- Unit tests (24 tests covering OrderModel, UUID anchor, buyer matching, canonicalization)
- GitHub Actions CI (Python 3.11 + 3.12, ruff + pytest)

[1.0.0]: https://github.com/Dangooy/trade-pipeline/releases/tag/v1.0.0
