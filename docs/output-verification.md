# Output Verification — Three Strategies for AI-Generated Documents

When an AI agent generates a document, it should not simply report "done." Instead, it should structurally verify the output against source data before reporting success.

Inspired by Anthropic's [claude-for-legal](https://github.com/anthropics/claude-for-legal) Citation Verifier pattern.

## Strategy A: Round-Trip Verification

**Best for**: Document generation (Excel, PDF, etc.)

**Flow**:
1. Generate the .xlsx file
2. Re-open the file with openpyxl
3. Read key cells, compare against source data

**Check items**:
- Row count: output rows == source data rows
- Entity name: header company name == expected seller entity
- Currency: header/column currency == expected currency
- Formula coverage: SUM formulas cover the correct row range

**Verdict**:
- All pass → report "verified" + summary
- Any fail → report which item failed, keep the file, let user decide

## Strategy B: Checklist Verification

**Best for**: Any document-producing workflow

**Flow**: After execution, output a structured summary for quick human verification:

```
── Output Verification ──────────────
✓ File: output/QT-2601.xlsx
✓ Line items: 12
✓ Total amount: USD 45,230.00
✓ Currency: USD
✓ Seller: ACME EXPORT TRADING CO., LTD.
✓ Buyer: Global Fasteners LLC
✓ Date: 19 May 2026
─────────────────────────────────────
```

**Critical rule**: Values in the summary MUST be read from the actual output file (round-trip), not recalled from memory.

## Strategy C: Cross-Reference Verification

**Best for**: Multi-document pipelines where documents reference each other

**Scenario matrix**:

| Source → Target | Check items |
|-----------------|-------------|
| Quotation → PI | Item names match, quantities match, prices match |
| PI → PL | Item names match, total quantity matches, total net weight matches |
| PI → CI | Unit prices match, total amounts match |
| CI ↔ PL | Full cross-validation (dedicated tool) |

## Failure Handling

1. **Never auto-fix**: Report the problem, don't retry automatically (avoids infinite loops)
2. **Never delete output**: Keep the file — user may manually correct it
3. **Suggest next step**: Tell user exactly which item mismatched, likely cause, and recommended action
