# 共享订单资料

使用 WorkBuddy 可写的业务目录。每个订单只交付一份当前结果。当前文件以提交回执的绝对路径为准，修订成果和订单记录保存在业务目录下的 `.workbuddy-orders/`。历史文件和中断的未提交文件留在内部目录。初次交付前从用户所给来源组织一次快照。快照和私有文件留在业务目录，不作为附件发布。

```text
scripts/business.py <业务目录> documents draft <订单号> --source <业务来源路径> --snapshot <快照JSON路径> --documents pi ci pl
```

将命令交给 WorkBuddy 可用的 Python 3.11+ 运行。首次自动使用随包的 Python 组件准备独立环境。准备中断后重试相同命令，已有的可用隔离环境会直接复用。只传用户实际需要的类型。每个来源用一次 `--source`；后续只需要同一来源时省略该项。格式示意仅作为字段说明，其他项按实际资料填写：

```json
{
  "details": {"currency": "CNY", "price_unit": "CNY/MPCS"},
  "items": [{"description": "示例零件", "quantity": 1000, "unit": "pcs", "unit_price": 24}],
  "evidence": {
    "details.currency": ["source", "报价!B2"],
    "details.price_unit": ["source", "报价!D2"],
    "items.1.description": ["source", "报价!A6"],
    "items.1.quantity": ["source", "报价!B6"],
    "items.1.unit": ["source", "报价!C6"],
    "items.1.unit_price": ["extracted", "报价!D6，币种或原值还需核对"]
  }
}
```

- `source` 表示附件明确载明且可定位的原值，也用于无歧义的等价写法，例如将 CNY/1,000 PCS 规范为 CNY/MPCS，并保留原写法及位置。遇到歧义的 OCR、推断或配置候选，标为 `extracted`，不用于正式值或金额。用户确实确认的才写 `confirmed` 并注明确认范围。未解决的冲突字段省略，受影响的金额留待核算。选择资料与确认正式出单分别处理。
- 订单字段 `seller`, `seller_address`, `buyer`, `buyer_address`, `currency`, `price_unit`, `payment`, `delivery`, `lead_time`, `port_loading`, `port_destination`, `date`（YYYY-MM-DD）, `pi_number`, `ci_number`, `bank_name`, `bank_account`, `swift`。实际装运字段是 `gross_kg`, `pallets`, `measurement_m3`, `packing`。日期、条款和适用格式取本单业务依据。
- 商品字段 `description`, `spec`, `material`, `finish`, `quantity`, `unit`, `unit_price`, `quoted_weight_kg`。实际字段为 `shipped_quantity`, `invoice_unit_price`, `net_kg`, `cartons`。净重是本行总净重，金额使用同一确认口径。正式开票、实发和包装字段请用 `实际资料.xlsx#Shipment!B7` 一类可定位的附件原值。把工作簿另加一个 `--source` 参数。程序核对工作表用途、表头或字段名、对应商品及数值。报价页、未定位引用、取错列或数值不符时，该字段留待确认。报价、历史订单和包装预设均不能作为本单实际数据。当前模板要求行单位明确且一致。
- 核对取 `check`，它只返回资料与缺项。需要编辑时用 `snapshot <订单号>` 读取已保存的共享资料，改动有依据的字段和对应证据，提交新快照并加 `--sync`。原件变化时先重新读取，再把更新的来源和快照一并提交。
- `review` 返回能正式出单的类型、实际采用的资料和有效 10 分钟的核对编号。展示核对内容后，按相同订单、资料、范围和 `--sync` 选项用 `formal --review-token <编号>`。按返回确认范围打开桌面弹窗。用户确认通过后，一次交付合格的正式单据与其余请求类型的内部稿。所有类型都欠资料时用 `draft`，无需弹窗。资料变化后重新核对。
- 首轮、修订、正式出单均将已提交回执的 `delivery_reply` 整段原样用于最终回复。先连续列完所有文件链接，每份一行，再列各单据的待确认项和待核算金额。发完这段即结束。`delivery_markdown` 是仅含链接的兼容字段。`missing` 用于正式出单校验。`--sync` 只交付本次变更的单据。

- 用户直接提供实际数据、没有可核对的结构化表格时，将拟核实字段标为 `confirmed`，注明用户给出的依据。先在对话展示数据，再用 `confirm-actuals <订单号> --source <业务资料> --snapshot <快照>` 打开「核对实际资料」窗口。本人核对并点击确认后再做 `review` 和正式出单确认。单纯把证据写成 `confirmed` 不会通过程序核对。只改报价数量时，已核实的实发数据继续使用。
- 命令返回异常或交付中断时，用 `status <订单号> --snapshot <本次快照> --documents <本次类型>` 查询，原命令有新来源时也传相同的 `--source`，若用了 `--sync` 也照传。只有 `status=committed` 且回执的动作和单据范围与请求相符，才用返回的 `delivery_reply` 继续交付。若回执为 `pending`、`blocked` 或 `not_committed`，先说明影响，重新运行可重复的草稿操作，正式结果重新核对并由用户确认。不要删除暂存文件或改写已交付文件。

## 分步出单的交付汇总

分步生成了本轮要交付的单据时，最后调用一次只读汇总，同时传入本轮各次已提交回执中的对应文件绝对路径（`documents.<类型>.file.path`，恢复回执是 `documents.<类型>.path`）。例如先提交 PL，再提交 PI：

```text
scripts/business.py <业务目录> documents delivery <订单号> --documents pi pl --file <本轮PI绝对路径> --file <本轮PL绝对路径>
```

只传本轮应该交付的当前文件，每种一份。修订时只传本轮更新的文件。成功后只输出这一段 `delivery_reply`。汇总只读现有成果，不能替代中断恢复或正式出单确认。若返回 `blocked` 或 `pending`，先核对失败或中断的是哪一步，避免交付旧文件或拼接草稿链接。取消后只完成一种单据时，使用该次已提交的回复正常收尾。
