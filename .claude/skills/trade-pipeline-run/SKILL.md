---
name: trade-pipeline-run
description: Execute the trade document pipeline (RFQ → Quotation → PI → CI → PL) or price write-back
triggers:
  - 处理询价单
  - 生成报价单
  - 做报价
  - run pipeline
  - generate quotation
  - 帮我出单
  - 价格填好了
  - 回写价格
---

# Trade Pipeline Run — Execute the Document Pipeline

## Trigger

When the user says: 处理询价单, 生成报价单, 做报价, 做PI, 做CI, 做PL, 跑管线, run pipeline, generate quotation, process inquiry, 处理这个Excel, 帮我出单

## Prerequisites

Before running, verify in order:

1. **Current directory**: must contain `trade_pipeline/` directory. If not, `cd` to the repo root.

2. **Installation check**: run `trade-pipeline --help`. If command not found, try `python -m trade_pipeline --help`. If both fail, prompt:
   ```
   管线未安装。请先在项目根目录（包含 pyproject.toml 的目录）运行：
   python -m pip install -e .
   ```

3. **Config check**: Read `trade_pipeline/config/config.yaml`.
   - If seller `name_en` contains "ACME EXPORT" or buyer email contains ".example.com" → inform user:
     "当前使用示例配置，可以跑 demo 体验。真实业务请先说"初始化配置"运行 init skill。"
   - Continue regardless (demo mode is fine).

## Flow 1: Pipeline Execution

### Step 1: Collect Input

Use AskUserQuestion to ask:

**Question 1** — 询价单路径:
- If user already provided a file path in their message, use it directly
- Otherwise ask: "询价单 Excel 文件路径？"
- Verify the file exists with Read tool

**Question 2** — 订单号:
- Ask: "订单号？（用于命名输出文件）"
- Options can include suggestions like DEMO, or user types custom

**Question 3** — 选择客户:
- Read `trade_pipeline/config/config.yaml`, extract buyer keys and name_en
- Use AskUserQuestion with options:
  - Each configured buyer: `buyer_id — name_en`
  - `_new — 新客户（buyer 信息填 TBD）`
  - "Other" for manual input
- Maximum 4 options (AskUserQuestion limit), prioritize most recently used

### Step 2: Execute

Run via Bash:
```bash
trade-pipeline --input <path> --order <order_no> --buyer <buyer_id>
```

If `trade-pipeline` command not found, fallback to:
```bash
python -m trade_pipeline --input <path> --order <order_no> --buyer <buyer_id>
```

Do NOT add `--interactive` flag (default to review.json mode for safety).

### Step 3: Report Results

If successful (exit code 0):
- List all 6 generated files with paths
- Show key stats: item count, buyer, seller, currency
- Prompt next step: "报价单已生成，单价列（黄色高亮）待填写。填好后说'价格填好了'触发回写。"

If buyer match failed (output contains "review.json"):
- Show the review.json path
- Explain: "buyer 匹配失败，已生成 review.json。"
- Show candidate buyers from the output
- Offer to help edit review.json:
  - "选择正确的 buyer，我帮你编辑 review.json 并重新运行。"

## Flow 2: Price Write-Back

### Trigger
价格填好了, 回写价格, 重新生成PI/CI, price update, 单价已填

### Steps

1. Locate the most recent quotation and model files:
   - Look in `output/<most_recent_order>/` for `*_quotation.xlsx` and `*_model.json`
   - Or ask user to confirm paths

2. Execute:
   ```bash
   trade-pipeline --price-update <quotation_path> --model <model_path>
   ```

3. Report:
   - How many prices were updated
   - Whether PI/CI were regenerated
   - If errors occurred: show errors, advise to fix and retry

## Notes

- This skill handles the runtime execution. For first-time configuration, use the `trade-pipeline-init` skill.
- All generated files go to `output/<order_no>/`.
- The pipeline generates 6 files: rfq.json, model.json, quotation.xlsx, pi.xlsx, ci.xlsx, pl.xlsx.
- Price column in quotation is yellow-highlighted — this is the manual input point.
- After price write-back, PI and CI are regenerated with actual amounts.
