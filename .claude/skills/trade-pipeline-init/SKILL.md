---
name: trade-pipeline-init
description: Interactive setup wizard for first-time trade-pipeline configuration
triggers:
  - 初始化配置
  - setup
  - configure trade pipeline
  - 第一次使用
  - init
---

# Trade Pipeline Init — Interactive Setup Skill

## Trigger
When the user says "初始化配置", "setup", "configure trade pipeline", "init", "第一次使用", or when `trade_pipeline/config/config.yaml` contains example/placeholder data (seller name is "ACME EXPORT").

## Behavior

Use AskUserQuestion to guide the user through configuring their trade pipeline. Collect all information first, then write `config.yaml` in one step.

### Step 1: Company Info

Ask with AskUserQuestion (multiSelect: false):
- "你的公司英文名？" — free text input (user selects "Other")

Then ask:
- "公司中文名（可选）？"
- "公司地址？"
- "联系人姓名？"
- "联系邮箱？"
- "联系电话？"

These can be combined into 2-3 rounds of AskUserQuestion, grouping related fields.

### Step 2: Trade Terms

Ask with AskUserQuestion options:
```
question: "默认贸易条件？"
options:
  - label: "FOB"
    description: "Free On Board — 卖方交到港口，买方负责运输"
  - label: "CIF" 
    description: "Cost, Insurance, Freight — 卖方负责运费+保险到目的港"
  - label: "DDP"
    description: "Delivered Duty Paid — 卖方全包到买方门口"
  - label: "EXW"
    description: "Ex Works — 买方自提"
```

### Step 3: Currency & Port

Ask with AskUserQuestion options:
```
question: "默认币种？"
options:
  - label: "USD"
  - label: "CNY"
  - label: "EUR"
```

```
question: "默认装运港？"
options:
  - label: "QINGDAO,CHINA"
  - label: "SHANGHAI,CHINA"
  - label: "NINGBO,CHINA"
```

### Step 4: Payment & Lead Time

Ask:
- "付款条件？" (default: "30% T/T deposit; 70% before shipment")
- "交货期？" (default: "45-60 days after deposit")

### Step 5: First Buyer (Optional)

Ask:
```
question: "现在添加第一个客户吗？"
options:
  - label: "是，添加客户"
  - label: "跳过，稍后再加"
```

If yes, ask buyer name, address, contact, email.

### Step 6: Write Config

After collecting all info, generate the YAML config and write to:
`trade_pipeline/config/config.yaml`

Use the following structure:
```yaml
sellers:
  <seller_id>:
    name_cn: <中文名>
    name_en: <英文名>
    address: <地址>
    contact: <联系人>
    tel: <电话>
    email: <邮箱>
    bank: { name: "", swift: "", account_no: "" }

buyers:
  <buyer_id>:  # if provided
    name_en: <名称>
    legal_names: [<名称>]
    aliases: [<简称>]
    address: <地址>
    contact: <联系人>
    email: <邮箱>

format_defaults:
  standard:
    seller_id: <seller_id>
    currency: <币种>
    price_unit: "<币种>/PC"
    terms_id: "default_<币种小写>"

terms_templates:
  default_<币种小写>:
    payment: <付款条件>
    delivery: "<贸易条件> <装运港>, Incoterms 2020."
    lead_time: <交货期>
    validity: "10 days"
    packing: "Standard export packaging: 25 kg cartons, Euro pallets."
    quality: "100% inspection before shipment."

defaults:
  port_of_loading: <装运港>
  pi_number_pattern: "PI-{order_no}"
  ci_number_pattern: "CI-{order_no}"
  quote_no_pattern: "QT-{order_no}"
  date_format: "%d %B %Y"

packing:
  carton_weight_kg: 25
  pallet_self_weight_kg: 28
  cartons_per_pallet: 36

pl_profiles:
  default:
    pl_config: standard
    packing_profile: standard_25kg

cache:
  dir: .cache/understanding
  prompt_version: v1.0
  schema_version: v1.0
  enabled: true

ocr_review:
  force_review_fields: [description, standard, quantity, unit, weight_kg]
  confidence_threshold: 0.90
```

Seller ID generation: take the first 2 meaningful words from the English name, lowercased, joined by underscore. Skip words like "co", "ltd", "inc", "limited".

### Step 7: Confirm

Show the user a summary:
```
Seller: <英文名> (id: <seller_id>)
Terms:  <贸易条件> | Currency: <币种> | Port: <装运港>
Buyer:  <客户名> (if added)

Config written to: trade_pipeline/config/config.yaml

Quick demo:
  python -m trade_pipeline --input examples/sample_inquiry.xlsx --order DEMO --buyer <buyer_id or _new>
```

## Notes
- The CLI version (`python -m trade_pipeline init`) is still available as a fallback
- This skill provides a better UX within Claude Code using native dialog controls
- Bank info can be added later by editing config.yaml directly
