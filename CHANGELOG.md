# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`.gitattributes`**：声明 `* text=auto eol=lf` 与二进制类型。属**预防性**措施——本仓库未实际发生过换行符问题，但仓库曾在 Windows 上开发，而共用同一套代码的私有仓库出现过「工作树 CRLF / 仓库 LF」导致的假改动。声明后 git 在比较与提交时统一归一化为 LF，这类假改动不会再出现。

### Changed

- **CI 加固**（`.github/workflows/ci.yml`、`pyproject.toml`）：
  - **新增覆盖率门槛 80%**（`[tool.coverage.report] fail_under`）。此前 CI 只跑 `--cov-report=term`，把覆盖率打印到日志却**不强制**——覆盖率可以一路悄声下滑而构建依然是绿的。改动前实测 82%（3099 语句 / 566 未覆盖），门槛留了一点缓冲。放在 pyproject 而非 CI 的 `--cov-fail-under`，是为了本地 `pytest --cov` 也受同一处配置管理，且门槛只存在一处。
  - **ruff 改为检查全仓库**（原为 `ruff check trade_pipeline/ tests/`）。此前 `scripts/` 与 `examples/` 下的 4 个 Python 文件不被检查，其中 `scripts/check_version.py` 正是版本一致性检查自身。已实测这 4 个文件本就通过 ruff，扩大范围无新增告警。
  - **Actions 升级**：`actions/checkout` v4 → v7、`actions/setup-python` v5 → v7。旧版 action 依赖的运行时会被逐步淘汰，届时会出现与代码改动无关的构建失败。
  - **矩阵加 `fail-fast: false`**：此前一个 Python 版本失败会直接取消另一个，看不出问题是出在单个版本还是全部。
  - **矩阵新增 Python 3.13**（原为 3.11 / 3.12）：`pyproject.toml` 声明 `requires-python = ">=3.11"`，但此前只测到 3.12，意味着 3.13+ 属于「声称支持却未验证」。本机 Python 3.14 跑全部 311 个测试通过，是本次扩测的依据。

## [1.4.3] - 2026-08-16

第三批外部审计修复（C 系列，2608 审计遗留清单至此**清零**，记录见 `docs/adversarial-review-2608-external.md`）。

### Fixed
- **LLM 4000 字符截断静默丢行（C1，2607 审计即已点名）**（`understanding/llm_parser.py`）：询盘内容超 4000 字符时此前无任何信号——超出部分的明细行不进解析、结果照常缓存，用户无法得知数据不全。现在超限时打印 WARNING，并在结果上携带 `_llm_truncated` 标记，由 assembler 写入 `meta.parser_notes` 供用户与后续校验消费。
- **解析降级标记被 assembler 丢弃（C2）**（`understanding/understanding/assembler.py`）：`llm_parser` 打的 `_llm_degraded` 标记此前在 assembler 里被硬编码（`parser_model="rules"`、`review_status="clean"`）覆盖，"显式标记降级"的设计落空——用户拿到的是降级结果却显示 clean。现在 `meta.parser_model`（llm / llm_fallback_rules / rules）、`meta.review_status`（clean / degraded）、`meta.parser_notes`（降级原因、截断提示）如实反映解析来源与质量。
- **CI 吨计价数量列整数格式（C3）**（`writers/ci_writer.py`）：tons 数量如 12,345.6 被 `#,##0` 格式化成 12,346——与 PI 的两位小数不一致，显示值与金额公式输入脱节。吨计价（format 为 washers_mar 或 price_unit 含 TON）改为 `#,##0.00`，件计价保持整数不变。
- **欧洲数字格式解析错误（C4）**（`understanding/llm_parser.py`）：`_to_float` 此前把欧洲格式当美式处理——`"1.234,56"` → 123456、`"12,5"` → 125（数量错一个数量级），无法解析时静默归 0。现在支持欧洲格式（点作千分位、逗号作小数点；歧义模式如 `"1.234"` 维持美式解读不猜），解析失败打印 WARNING 并返回 0.0，提示人工核对来源单元格。

### Added
- 15 个新测试（296 → 311）：欧洲格式矩阵（含负数、百万级分组、美式回归）、解析失败 WARNING 断言、assembler 消费降级/截断标记四种组合、CI 吨/件/吨单价三档数量格式。

## [1.4.2] - 2026-08-16

第二批外部审计修复（B 系列，完整记录见 `docs/adversarial-review-2608-external.md`）。

### Fixed
- **buyer 匹配中间剥除碰撞（B1）**（`understanding/buyer_matcher.py`）：`_core_name` 此前从名字**任意位置**剥法律后缀 token，`"Alpha Co Trading Ltd"` 中间的 `co` 被剥后核心名与另一家 `"Alpha Trading LLC"` 相等，唯一命中即接受——A 客户的单据抬头会写上 B 客户。现改为只剥开头连续段（俄语前缀惯例，如 `ООО`）+ 结尾连续段（英语后缀链，如 Limited Liability Company），中间的法律词保留。**行为变化**：部分此前静默匹配通过的输入现在会硬阻断进 review.json 人工确认——错配风险交还给人，这是修复目的。
- **PL 每箱重与净重舍入不自洽（B3）**（`writers/pl_writer_lite.py`、`writers/ci_writer.py`、`validation/cross_doc.py`、`pipeline/main.py`）：此前行净重=真实净重、每箱重=round(净重/箱数)，100kg 分 3 箱时 33.33×3=99.99≠100，报关算术核查看的正是这组关系。现改为行净重=每箱重×箱数（单据内 `KGS/CTN×CTS=NET`、`Σ行净重=合计` 恒成立；与磅秤实重偏差 ≤0.005×箱数 kg，低于称重精度）；CI 页脚净重改为优先读 PL 回写的 `derived.total_net_weight`（与毛重 T1 的同源模式对称），PL 未运行时回退独立累加；新增跨单净重校验 `check_ci_pl_net_weight`（0.01 容差）接入两处生成流程。

### Added
- **版本一致性检查（B2）**（`scripts/check_version.py`、`.github/workflows/ci.yml`）：CI 新增独立 job，强制 `pyproject.toml` ↔ `.claude-plugin/plugin.json` 版本相等、且 CHANGELOG 有对应版本小节，违反即失败。防的是 v1.4.1 收尾时发现的真实事故——plugin.json 落后两个版本无人察觉。
- 20 个新测试（276 → 296）：中间剥除碰撞负样本（"Alpha Co/Holdings/Limited Trading"）、核心名新语义固化、俄语前缀模糊回归、版本检查脚本（含对仓库自身）、PL 行自洽与整除不变、Excel 单元格级 D×C==F 断言（此前无任何 D 列断言）、CI 读 PL 回写净重与回退、端到端两单净重相等、跨单净重校验矩阵。

## [1.4.1] - 2026-08-15

第三轮外部审计修复（问题编号 A1-A7，完整审计记录见 `docs/adversarial-review-2608-external.md`；与 2026-07 的两轮 T 系列审计不重叠）。本轮主题：**金额与重量路径上的字段口径一致性、输出校验**——这类路径错一个数，落到真实单据上就是直接的金钱或清关风险。

### Fixed
- **吨计价下 PI 重量列单位混淆（A1）**（`models/order_model.py`、`writers/pi_writer.py`、`writers/ci_writer.py`、`writers/pl_writer_lite.py`）：`weight_kg` 缺失时，PI 会把 `kg_mpcs`（每千件重量）原值写进 "Weight (kgs)" 列，而吨计价的金额公式 `=M/1000*N` 引用该列——等于用"每千件重"当"总重"算钱；同一行 CI 走 `compute_amount` 只认 `weight_kg` 得 0.0，PI 与 CI 尽管共享 `amounts.py` 单一来源仍会分叉。新增 `effective_weight_kg()` 统一派生（`weight_kg → 单件重×数量 → kg_mpcs×数量/1000 → None`，0.0 视为合法重量不被吞掉），PI / CI / PL lite 三处共用同一来源。
- **CI 与 PL 净重口径分裂（A2）**（`writers/ci_writer.py`）：CI 净重合计只认 `weight_kg`，PL 却按三个来源派生——只有 `kg_mpcs` 的商品，PL 打印真实净重、CI 打 `N.W.: 0.00KGS`，清关单证对不上。两单现在都走 `effective_weight_kg()`。
- **LLM 返回无 schema 校验（A3）**（`understanding/llm_parser.py`、`understanding/canonicalizer.py`、`understanding/assembler.py`）：解析成功的 LLM 输出此前只查一层 `isinstance(dict)` 就写入缓存——`items: null` 会让 canonicalizer 崩溃（`.get` 的默认值对显式 null 不生效）、字符串数字数量会让 assembler 的 `sum()` 崩溃，坏结果还会被缓存持续污染重跑。新增 `_validate_rfq_schema()`（结构校验 + 数值字符串规范化（含千分位逗号）+ 负数量拒绝），校验失败走既有的显式降级路径（打标记、不进缓存）；下游补 `or []` 空值防护。
- **不可信隔离标签可被闭合逃逸（A4）**（`understanding/llm_parser.py`）：询盘内容里出现字面量 `</untrusted_document_content>` 即可闭合 T4 建立的提示词隔离标签，让其后的伪指令逃出隔离区。`_strip_untrusted_tags()` 现于包裹前剥离内容中的标签字面量。
- **`price_unit`/`currency` 为显式 null 时 PI 崩溃、CI 渲染 "None"（A5）**（`understanding/assembler.py`、`writers/pi_writer.py`、`writers/ci_writer.py`）：`.get()` 的默认值不覆盖显式 null（LLM 返回 `"price_unit": null` 即可触达），PI 的 `.upper()` 直接 AttributeError；CI 无币种兜底会打出 `None/ FOB PRICE`、`SAY: NONE … ONLY.`。根因在 assembler 修复（`or` 兜底），writer 层再加第二道防线，与 quote_writer 口径一致。
- **PL 空订单 / 除零无守卫（A7）**（`writers/pl_writer_lite.py`）：items 为空会静默产出"1 个托盘、毛重=托盘自重"的空货装箱单；`cartons_per_pallet=0` 除零崩溃。现在入口处双守卫，均以 ValueError 拒绝生成。

### Changed
- **报价单 Amount 列改为活公式（A6）**（`writers/quote_writer.py`）：非重量模式下表头写着 "Amount（币种）"、数据列却固定写 `weight_kg`——金额从未被计算，列恒为空（有重量数据时甚至显示公斤数）。现在复用 `amounts.amount_formula()`（`=`数量×单价` / `=数量/1000×单价`），销售填价后金额即时算出；吨计价缺重量数据时诚实留空。
- 新增 27 个测试（249 → 276，`tests/test_audit_fixes_2608.py`）：重量派生的优先级/0.0 合法性/兜底链、吨计价 PI 列值、null price_unit/currency 存活性、CI↔PL 净重一致、schema 校验接受/拒绝矩阵、标签剥离、报价单公式模式、PL 守卫。

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

[1.4.3]: https://github.com/Dangooy/trade-pipeline-skill/releases/tag/v1.4.3
[1.4.2]: https://github.com/Dangooy/trade-pipeline-skill/releases/tag/v1.4.2
[1.4.1]: https://github.com/Dangooy/trade-pipeline-skill/releases/tag/v1.4.1
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
