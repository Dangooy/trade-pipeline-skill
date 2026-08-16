# 外部审计与修复记录（2026-08-15）

> 审计方法：三路并行精读（writers / understanding / 校验与金额计算核心）+ 实证验证
> （249 既有测试、ruff、端到端 demo 跑通、生成文件开箱检验），全部高严重度
> 指控均经代码级复核后才确认。本文档记录确认的问题（A1-A7）、修复方式与
> 验证证据，供后续审计与维护者对照。
>
> 与 2607 两轮审计（T 系列）不重叠：本轮发现均为既有审计未覆盖的字段口径
> 与输出校验问题。

## 确认问题与修复

### A1（高）PI 重量列单位混淆，吨计价金额错误
`writers/pi_writer.py` 在 `weight_kg` 缺失时把 `kg_mpcs`（每千件重）原值写入
"Weight (kgs)" 列 M，而吨计价金额公式 `=M/1000*N`（`models/amounts.py`）引用
该列——等于用"每千件重"当"总重"算钱；同一行 CI 走 `compute_amount` 只认
`weight_kg` 得 0.0，PI/CI 同源设计被破坏。附带：falsy 判断会把合法的
`weight_kg=0.0` 也替换掉。

**修复**：新增 `models/order_model.effective_weight_kg()` 统一派生口径
（`weight_kg → weight_kg_per_piece×qty → kg_mpcs×qty/1000 → None`），
PI / CI / PL lite 三处共用同一来源（PL lite 原有内联逻辑改为调用该函数，行为不变）。

### A2（高）CI/PL 净重口径分裂
`writers/ci_writer.py` 净重合计只认 `weight_kg`；PL lite 认三个来源。只有
`kg_mpcs` 的商品：PL 显示真实净重、CI 打 `N.W.: 0.00KGS`——清关单证对不上。

**修复**：CI 改用 `effective_weight_kg()`（同 A1）。

### A3（高）LLM 返回零 schema 校验，坏数据进缓存
`understanding/llm_parser.py` 解析成功后仅 `isinstance(rfq, dict)` 即返回并写
缓存：`items: null` 使 canonicalizer 的 `.get("items", [])` 拿到 None 直接
TypeError；`quantity` 为字符串数字时 assembler 的 `sum()` 崩溃；坏结果被缓存
持续污染重跑。

**修复**：新增 `_validate_rfq_schema()`（结构校验 + 数值字符串规范化 +
负数量拒绝），失败走既有降级路径（显式标记、不进缓存）；canonicalizer /
assembler 补 `or []` None 防护。

### A4（高）提示词隔离标签可被内容闭合穿透
T4 建立的 `<untrusted_document_content>` 标签防护，内容未剥离标签字面量——
询盘单元格里的 `</untrusted_document_content>` 可闭合隔离标签让伪指令逃逸。

**修复**：`_strip_untrusted_tags()` 剥离内容中出现的开/闭标签字面量，内容其余
部分保留。

### A5（中）`price_unit`/`currency` 显式 null 时 PI 崩溃、CI 渲染 "None"
根因在 `understanding/assembler.py`：`.get()` 默认值不覆盖显式 null（LLM 返回
`"price_unit": null` 可达），PI 的 `.upper()` 直接 AttributeError；CI 无币种
兜底会打出 `None/ FOB PRICE`、`SAY: None … ONLY.`。

**修复**：assembler 改 `or` 兜底（根因），PI/CI writer 层再加第二道防线
（与 quote_writer 一致的 `CNY` / `CNY/MPCS` 默认）。

### A6（中）报价单 Amount 列名不副实
非重量模式表头是 `Amount (currency)` 但数据行固定写入 `weight_kg`——金额从未
被计算，列恒空；items 带重量数据时显示公斤数。

**修复**：改为活公式，复用 `models/amounts.amount_formula()`（千件计价
`=E/1000*F`，普通 `=E*F`），销售填价后金额自动算出；吨计价无重量数据时诚实
留空。

### A7（中）PL 空订单/除零无守卫
空 items 静默产出"1 托、毛重=托盘自重"的空货 PL；`cartons_per_pallet=0` 除零
崩溃。

**修复**：`_compute_packing()` 入口双守卫，ValueError 拒绝生成。

## 未修复（已知，留待后续）

本轮确认但未在本批修复（避免单批改动过大）：buyer 匹配从名字中部剥法律
后缀词导致核心名碰撞、PL 每箱重四舍五入的行内自洽性（33.33×3≠100）、
CI 吨数列整数格式化、`_to_float` 欧洲数字格式静默归零、LLM 4000 字符截断
（2607 审计已点名）、降级标记 `_llm_degraded` 在 assembler 被丢弃。

## 第二批修复(B 系列,2026-08-16,v1.4.2)

针对本文档"未修复"清单中的前两项,外加一项流程防线:

- **B1(高)buyer 匹配中间剥除碰撞**:`_core_name()` 此前从**任意位置**剥法律
  后缀 token——`"Alpha Co Trading Ltd"` 中间的 `co` 被剥后,核心名变成
  `alpha trading`,与另一家 `"Alpha Trading LLC"` 相等,唯一命中即接受,
  A 客户的单据抬头写上 B 客户。修复:只剥**开头连续段**(俄语法律形式是
  前缀,`ООО Метиз` 的既有承诺保留)+ **结尾连续段**(英语后缀链),
  中间的法律词保留。行为变化:部分此前静默通过的碰撞输入现在硬阻断进
  review.json 人工确认——这是修复目的,不是回归。
- **B2(中)CI 版本一致性检查**:新增 `scripts/check_version.py` + CI 独立
  job,强制 `pyproject.toml` ↔ `.claude-plugin/plugin.json` 版本相等且
  CHANGELOG 有对应小节。防的是 v1.4.1 收尾时发现的真实事故:plugin.json
  落后 pyproject 两个版本无人察觉。
- **B3(中)PL 每箱重×箱数自洽**:行净重从"真实净重 round(2)"改为
  "每箱重×箱数"(100kg/3箱 → 33.33×3=99.99),单据内 `KGS/CTN×CTS=NET`
  与 `Σ行净重=合计` 恒成立(报关算术核查点);与实重偏差 ≤0.005×箱数 kg,
  低于称重精度。CI 净重改为优先读 PL 回写的 `derived.total_net_weight`
  (与毛重 T1 的同源模式对称,该字段此前写后无人读),新增跨单净重校验
  `check_ci_pl_net_weight` 作为回归护栏。

验证:296 测试全绿(276+20 新增);ruff 全过;端到端实测(10 行混合重量
来源订单):PL 10/10 行 D×C==F、Σ行净重==合计(6070.07)、CI 页脚
N.W. 与 PL 严格相等(6070.07)。

**仍未修复(更新后的遗留清单)**:LLM 4000 字符截断无标记(2607 已点名)、
`_llm_degraded` 标记被 assembler 丢弃、CI 吨数列整数格式化、欧洲数字
格式 `"1.234,56"` 静默归零、`_to_float` 无 warning。

## 验证证据

- **单测**：276 全绿 = 249 既有零回归 + 27 新增（`tests/test_audit_fixes_2608.py`，
  覆盖 A1-A7 每项的正反用例）；ruff 全过。
- **端到端**（询盘 → 报价单 → 填价 10 行 → 回写 → PI/CI/PL）：
  - 注入 `kg_mpcs=7.0, qty=60000` 的行，PI M 列显示 **420**（修复前为 7）；
  - 混合重量来源（5 行直接 + 5 行派生）下 CI 与 PL 均打出
    `N.W.: 6,070.00 KGS / G.W.: 6,266.00 KGS`（修复前 CI 打 600.00、PL 打 6070）；
  - 报价单 Amount 活公式在真实文件中生效（`=E11/1000*F11`）；
  - CI 总额 CNY 25,945.00 与逐行手算一致；生成前门禁（缺价拦停、警告需
    `--skip-warnings`）行为不变。
