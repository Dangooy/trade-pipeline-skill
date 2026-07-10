# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-07-10

Second adversarial-audit remediation (frozen-criteria benchmark round). An external audit with reproducible evidence confirmed a systematic CI/PL gross-weight mismatch, illegal amount-in-words output at boundaries, and several injection/robustness gaps. All confirmed findings (T1-T8) are fixed in this release.

### Fixed
- **CI/PL gross weight systematically inconsistent (T1)** (`pipeline/main.py`, `writers/ci_writer.py`): CI was generated before PL, so `model.derived.total_gross_weight` was always `None` at CI time and CI unconditionally fell back to the `nw*1.036` estimate, while PL printed the real pallet-based weight (net + pallets × pallet self-weight) — every order shipped with two different G.W. figures (e.g. 590.52 vs 598.0), diverging further on large orders. Generation order is now PI → PL → CI in both `_write_trade_docs` and `run_price_update`: PL writes back the real gross weight first, CI reads it (the estimate remains only as a fallback when PL fails). Verified: same order now prints identical G.W. on both documents.
- **`amount_to_words` illegal output at boundaries (T2)** (`writers/ci_writer.py`): cents were computed via float arithmetic and could round to 100 without carrying (`0.995` → "…AND ONE HUNDRED CENTS ONLY"), negative amounts lost their cents (`-5.5` → "MINUS FIVE ONLY"), and scale words stopped at MILLION (`1e9` → "ONE THOUSAND MILLION"). Now integer-cent arithmetic (`divmod(round(|amount|*100), 100)`) with a unified MINUS prefix, plus BILLION/TRILLION scales. CI is a legal document; this closes all known illegal-words paths.
- **SPRING LOCK WASHER misgrouped as FLAT WASHER (T7)** (`understanding/canonicalizer.py`): the generic `"WASHER"` branch preceded the specific `"SPRING LOCK WASHER"` branch in the if/elif chain, making the latter unreachable. Specific branch moved first.

### Added
- **Cross-document validation** (`validation/cross_doc.py`, new): after CI and PL are both generated, `check_ci_pl_gross_weight` compares their gross weights (0.01 kg tolerance) and emits a visible warning on mismatch — a regression guard for T1.
- **Formula-injection sanitization (T3)** (`writers/base_writer.py`, `writers/quote_writer.py`): `sc()`/`mc()` now prefix `'` to string values starting with `= + - @` so inquiry-derived text can never be written as a live Excel formula (`=cmd|…`, `=HYPERLINK(…)`); intentional formulas (amount columns, `=SUM` totals) are explicitly whitelisted via `formula=True`. `quote_writer`'s direct cell writes are routed through the same sanitizer.
- **LLM prompt isolation (T4)** (`understanding/llm_parser.py`): raw document text is wrapped in `<untrusted_document_content>` tags and the system prompt now instructs the model to treat it as untrusted data and ignore any instructions inside it.
- **`--use-llm` privacy disclosure (T5)** (README.md, CLAUDE.md, README_DEV.md): documents that `--use-llm` sends raw inquiry content (customer names, products, quantities) to the Anthropic API, is opt-in and off by default, and should be avoided for sensitive documents. (Flagged in `docs/adversarial-review-2607.md` since v1.3.0 but never documented.)
- **Input limits (T6)** (`extractors/excel_extractor.py`): 20 MB file-size and 5000-row caps with a clear `FileTooLargeError`; unbounded workbooks can no longer exhaust memory.
- 22 new tests (227 → 249 total): amount-in-words boundary/negative/large-number cases (previously zero coverage), sanitizer allow/deny cases, extractor limits (`tests/test_extractor.py`, new), cross-doc gross-weight rule, canonicalizer grouping regression.

### Changed
- **Dependency upper bounds (T8)** (pyproject.toml, requirements.txt): `openpyxl<4`, `pyyaml<7`, `anthropic<2`, `pytest<9`, `pytest-cov<7`, `ruff<1` — a major-version release of any dependency can no longer break a fresh install silently.

[1.4.0]: https://github.com/Dangooy/trade-pipeline-skill/releases/tag/v1.4.0

## [1.3.0] - 2026-07-09

Adversarial-review remediation. Two independent AI reviews (Claude Sonnet 5 self-review + Claude Fable 5 cross-check, both recorded under `docs/adversarial-review-2607*.md`) found buyer-matching false positives, a silent LLM-degradation path, and a silent price-column fallback — all capable of producing a structurally valid but factually wrong PI/CI without any error surfacing. This release closes those gaps.

### Fixed
- **Buyer fuzzy matching redesigned** (`buyer_matcher.py`): replaced unbounded bidirectional substring matching with "strip legal-form suffix, compare core names." Previously, short aliases (`"GF"`, `"Apex"`) participated in substring matching and could silently match unrelated companies (`"GF Industrial Supply"`, `"Apexon Software Ltd"`); a long legal name could also substring-match a completely different company sharing a prefix (`"Global Fasteners LLC"` vs `"Global Fasteners Trading LLC"`). Now: aliases are exact-match only; fuzzy matching strips legal suffixes (LLC/Ltd/GmbH/ООО/etc.) and requires the remaining "core name" to match exactly — extra real words (Trading, International) are rejected, suffix-only differences (Co vs Corp) are accepted; ambiguous matches across multiple buyers hard-block to `review.json` instead of picking one.
- **LLM parse fallback no longer silently swallows data errors** (`llm_parser.py`): `except Exception` was catching network errors, auth failures, and malformed-JSON responses identically and falling back to rules mode without any signal — a user who explicitly requested `--use-llm` for a complex inquiry could silently get lower-accuracy rules-mode output with no indication anything degraded. Now split into two paths: `anthropic.APIError` (network/timeout/auth) falls back silently as before (genuine infra fault), while response-parsing failures (`json.JSONDecodeError`, malformed schema) fall back **and** tag the result with `_llm_degraded` + a reason string.
- **Price write-back no longer silently misreads the wrong column** (`price_updater.py`): `_find_price_column` used to fall back to a hardcoded column F when the "Price" header couldn't be found — if a user reordered quotation columns, prices would silently be read from the wrong cell and written back incorrectly. Now raises `PriceUpdateError` instead of guessing.
- **Product-name translation no longer stops after the first match** (`canonicalizer.py`): a description containing multiple Chinese product names (e.g. "六角螺栓配平垫圈") only had the first one translated before the loop broke, leaving the rest in Chinese on customer-facing documents. Now replaces all matches; translation table iterates longest-term-first so short terms can no longer clip a longer term mid-match.
- **First-run demo experience**: `config.yaml`'s template ships with empty `sellers`/`buyers`, but no code path actually loaded `examples/demo_config.yaml` for the README/SKILL.md-advertised demo walkthrough — `python -m trade_pipeline --buyer global_fasteners` on a fresh checkout hard-blocked with an entity-resolution error. `load_config()` now merges the demo config into memory when `sellers` is empty (never writes to disk, never touches a real config).

### Added
- `_llm_degraded` flag is now consumed: `main.py` prints a visible warning (`⚠ 本次为降级结果`) with the failure reason whenever the LLM parse fell back due to a data/parsing error, instead of the degradation being invisible to the user.
- `trade-pipeline-run` SKILL.md: buyer-match-failure review flow must now resolve each candidate's `name_en` from `config.yaml` and show real company names via `AskUserQuestion` — `review.json`'s `candidate_values` only stores raw buyer_id strings, so showing the bare ids was not actionable for a user. The Skill may no longer infer/guess a buyer from context and write `resolved_value` without the user explicitly naming it.
- `trade-pipeline-run` SKILL.md: mandatory reminder after any PI/CI generation or price write-back — "PI/CI 是正式对外单证，发送给客户前请人工核对买家抬头、金额、税号是否正确." Automated precheck validates structure (missing fields, bad formats), not business correctness — it cannot catch a correctly-formatted document sent to the wrong buyer.
- 9 new tests: LLM-degradation three-path contract (`test_llm_parser_fallback.py`), missing-price-column hard block, buyer negative-match / suffix-variant cases (218 → 227 total).

### Docs
- `docs/adversarial-review-2607.md` — original adversarial review (Claude Sonnet 5)
- `docs/adversarial-review-2607-crosscheck.md` — independent cross-check and severity re-ranking (Claude Fable 5)

[1.3.0]: https://github.com/Dangooy/trade-pipeline-skill/releases/tag/v1.3.0

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
