# Trade Pipeline — 外贸单证自动化工具

[English](README_EN.md) | [Русский](README_RU.md) | [技术深度版](README_DEV.md)

<p align="center">
  <b>一份数据，自动出报价单、PI、CI、装箱单。<br>不用在多个 Excel 之间来回复制粘贴。</b>
</p>

<p align="center">
  <img src="cover.png" alt="Trade Pipeline 工作流程：从一份客户询价单自动生成报价单、形式发票、商业发票和装箱单" width="800">
</p>

---

## 怎么用：一个 AI 技能（Skill）

这是一个 **AI Agent 技能（SKILL.md 格式）**。装好后，你只需要用大白话对它说话——
「把这份询价单转成报价单」「客户确认了，出 PI/CI/PL」——AI 全程帮你跑完，不用记任何命令。

👉 安装和使用：[用 Claude Code](#use-skill) · [用腾讯 WorkBuddy](#use-workbuddy)

---

## 你每周是不是在做这些事？

- 客户发来询价 Excel → 手动把产品名、规格、数量**抄到**报价单里
- 客户确认后 → 手动把同样的数据**再抄一遍**做 PI
- 备货完成 → **又抄一遍**做 CI 和装箱单
- PI 里有个数量写错了 → CI、PL、报关资料**全跟着错**，逐个找逐个改
- 不同客户要不同的 PI 格式（俄罗斯客户要俄语、欧洲客户要英语）→ 维护**好几套模板**

**每份单据本质上是同一组数据的不同排版**，但你每次都在从零开始做。

Trade Pipeline 的解决方案很简单：**只维护一份订单档案，所有单据从这份档案自动生成。改一处，四份单据联动更新。**

---

## 它能帮你做什么

把一份客户询价 Excel **自动变成**以下全套单据：

| 单据 | 说明 |
|------|------|
| 📋 **报价单** | 公司表头、产品明细、单价列留空让你填 |
| 📄 **形式发票 PI** | 卖方/买方信息、付款条款、贸易条件 |
| 📄 **商业发票 CI** | 中英双语表头、唛头、装运信息、大写金额 |
| 📦 **装箱单 PL** | 分箱明细、箱数/重量/数量、托盘汇总 |

**报价单** — 黄色高亮列填单价，填完后一键回写到订单档案：

![报价单](docs/2601_quotation.png)

**形式发票 PI** — 卖方/买方表头、分组产品行、付款条款：

![PI](docs/2601_pi.png)

**商业发票 CI** — 中英双语、唛头、装运信息、SAY 大写金额：

![CI](docs/2601_ci.png)

**装箱单 PL** — 分组明细、箱数/箱重/数量/净重/毛重、托盘汇总：

![PL](docs/2601_pl.png)

---

## 适合谁用

| 你的情况 | 适合吗？ |
|---|---|
| 没有 ERP，靠 Excel + 邮件 + 微信处理单据 | ✅ **核心场景，直接用** |
| 有用友/金蝶/旺店通，但外贸单证支持弱 | ✅ 适合，补充单证前置和输出 |
| 用 Odoo / ERPNext 等开源 ERP | ✅ 可以作为询盘解析模块集成 |
| 用 SAP B1 / NetSuite / Dynamics 365，配置完善 | ⚠️ 必要性不大 |
| 年业务量上万单，已有 EDI/API 集成 | ❌ 请用企业级方案 |

### 最适合的画像

- 年订单量：**50–500 单**
- 产品 SKU：**< 5,000**
- 主要市场：**俄罗斯 / 东欧 / 南美 / 中东**
- 团队规模：**1–3 名外贸业务员**

> **完全不懂代码？** 没关系。看完上面几段你就能判断自己要不要用。安装和配置部分有一点命令行操作，但不需要编程知识——跟着复制粘贴就行。

---

## 和 ERP 是什么关系

Trade Pipeline **不是 ERP 替代品**。ERP 管库存、财务、应收应付、税务——这些它做不了也不打算做。

它补的是 ERP **前后两端**做不好的事：

| ERP 的短板 | Trade Pipeline 怎么补 |
|---|---|
| 客户发来的 Excel 询盘要**手工录入** | 自动提取产品数据 |
| 客户名拼写不一致（俄罗斯客户尤其多），ERP 匹配不到 | 4 层容错匹配，匹配不上就停下来让你选 |
| 每个客户要不同的 PI/CI 格式，改 ERP 模板要叫顾问 | 改一个配置文件就行，5 分钟搞定 |
| 报价单导出后客户改了行顺序，再导回来价格全错位 | 每行藏一个隐形标记，行序怎么变都不影响 |
| DIN/ISO/GOST 标准号没有专属字段 | 自动识别和规范化标准号 |

---

## 它不是什么

- ❌ **不是 ERP** — 不管库存、财务、税务
- ❌ **不是在线系统** — 没有账号、没有客服，数据全在你自己电脑上
- ❌ **不是多人协作平台** — 最适合 1–3 人小团队
- ❌ **不是"AI 自动做外贸"** — AI 只帮忙解析格式复杂的询价单，其他都是确定性规则
- ❌ **不直接对接海关** — 能准备报关行需要的数据，但不能直接提交单一窗口

---

## 先说清楚：适用什么行业

这个工具是我**给自己公司用**的，所以它是按**五金 / 紧固件行业**的特点做的：

- 计价**以重量为主**（KG / 吨）
- 产品规格相对固定（DIN / ISO / GOST 标准件那一套）
- 包装方式也比较标准

**如果你也是五金 / 紧固件行业**（螺栓、螺母、垫圈、标准件、线材、管件、法兰、轴承、密封件等），
改一下公司信息和翻译表基本就能用。

**如果你是别的行业**，规格、计价方式（按件 / 按套 / 按米）、重量和包装逻辑都不一样，
**这工具不能拿来即用**，需要自己改造——主要改这三处：

| 要改的地方 | 在哪 |
|---|---|
| 产品识别 / 中英翻译 | `understanding/canonicalizer.py` + 翻译表 |
| 计价模式（如果不是按重量） | `understanding/` 计价检测逻辑 |
| 单据模板（表头、字段、版式） | `writers/` 下的各个 Writer |

框架是通的，但适配工作量取决于你行业的复杂度。

> 一句话：**五金 / 紧固件能直接用，其他行业把它当一个可改造的底座。**

**比较吃力的行业**：服装（尺码矩阵复杂）、电子元器件（BOM 嵌套）、大宗散货（期货定价）、跨境电商（SKU 上万）——这些改造量较大，要有心理准备。

---

## 未来还想做的事

| 方向 | 说明 |
|------|------|
| 🔜 邮件辅助 | 读取客户信息和历史报价，帮你起草回复 |
| 🔜 跟进话术 | 基于订单状态生成 WhatsApp / 微信沟通草稿 |
| 🔜 报关数据包 | 自动整理报关行需要的货描、HS 编码、件数、毛净重 |
| 🔜 信用证审核 | 把 L/C 关键条款和订单数据自动比对 |
| 🔜 客户画像 | 统计每个客户的订货频次、金额、品类 |
| 🔜 报价建议 | 新询盘来了，自动参考历史成交价给报价员建议 |

> 以上是未来扩展方向，当前版本还没有。标 🔜 的不代表马上就有。

---

<details>
<summary><b>想试试？点这里看安装和使用方法</b></summary>

## 准备工作

你的电脑上需要先安装两样东西（如果已经有了就跳过）：

| 软件 | 用途 | 安装指南 |
|------|------|----------|
| **Python 3.12 或更高** | 运行这个工具 | [python.org/downloads](https://www.python.org/downloads/) |
| **Git** | 下载代码 | [git-scm.com/downloads](https://git-scm.com/downloads/) |

> 不确定有没有？打开命令行（Windows 按 Win+R 输入 `cmd`，Mac 打开"终端"），输入 `python --version` 和 `git --version`，能显示版本号就说明有了。

## 安装

<a id="use-skill"></a>
### 用 Claude Code 安装和使用

如果你还没用过 [Claude Code](https://claude.ai/code)：它是 Anthropic 官方的 AI 编程 / 自动化工具，装一次以后做单据、写邮件、整理数据都能用。装好插件后，**直接用大白话对它说话**就行，不用记任何命令。

**第 1 步：克隆并安装核心引擎**

```bash
git clone https://github.com/Dangooy/trade-pipeline-skill.git
cd trade-pipeline-skill
pip install -e .
```

**第 2 步：在 Claude Code 里加载插件**

本仓库自带 Claude Code 插件（`.claude-plugin/plugin.json`），内含两个 Skill：

| Skill 名 | 作用 |
|---|---|
| `trade-pipeline-init` | 首次配置向导（公司信息、贸易条件、第一个客户） |
| `trade-pipeline-run` | 执行单证流水线 / 价格回写 |

在仓库目录下启动 Claude Code，用 `/plugin` 命令把本地仓库作为插件加载（首次需要信任本目录）。加载后两个 Skill 会自动注册。

**第 3 步：直接对话**

```text
初始化配置                         → 触发 trade-pipeline-init，一步步问你公司信息
把 examples/sample_inquiry.xlsx 转成报价单   → 触发 trade-pipeline-run，自动跑完整条流水线
客户确认了，回写价格并出 PI/CI/PL          → 自动完成价格回写 + 生成正式单据
```

> Skill 会在背后跑一套确定性的引擎来生成单据，你不用手敲任何参数——把要做的事说给 Claude，它帮你拼好。

<a id="use-workbuddy"></a>
### 用腾讯 WorkBuddy 安装和使用

国内用 [WorkBuddy](https://codebuddy.cn/work)（腾讯的桌面 AI 智能体）的同学也能用——它兼容这种 SKILL.md 技能格式，把技能目录拷进去就行。

> **前提**：电脑已装 Python 3.11+ 和 Git。本技能底层会调用 Python 引擎，所以这一步不能省。

**Windows（PowerShell）**

```powershell
# 1. 下载项目并安装引擎
git clone https://github.com/Dangooy/trade-pipeline-skill.git
cd trade-pipeline-skill
pip install -e .

# 2. 把两个技能拷进 WorkBuddy 技能目录
mkdir "$env:USERPROFILE\.workbuddy\skills" -Force
Copy-Item -Recurse -Force ".\.claude\skills\trade-pipeline-init" "$env:USERPROFILE\.workbuddy\skills\"
Copy-Item -Recurse -Force ".\.claude\skills\trade-pipeline-run"  "$env:USERPROFILE\.workbuddy\skills\"
```

**Mac / Linux（终端）**

```bash
# 1. 下载项目并安装引擎
git clone https://github.com/Dangooy/trade-pipeline-skill.git
cd trade-pipeline-skill
pip install -e .

# 2. 把两个技能拷进 WorkBuddy 技能目录
mkdir -p ~/.workbuddy/skills
cp -r .claude/skills/trade-pipeline-init ~/.workbuddy/skills/
cp -r .claude/skills/trade-pipeline-run  ~/.workbuddy/skills/
```

装完后，在 WorkBuddy 对话里手动触发即可：

```text
@trade-pipeline-run 把这份询价单转成报价单
```

> 注：WorkBuddy 跑的是国产模型（混元 / DeepSeek / GLM 等），不是 Claude。技能的提示词是按 Claude 的理解习惯写的，换模型后偶尔触发或步骤理解会有偏差——第一次跑不顺很正常，欢迎提 issue 反馈。

## 首次使用配置

因为报价单、PI、CI 上都要打印你的公司信息，所以第一次用之前需要填一些基本信息。

在 Claude Code 里对它说 **「初始化配置」**（会触发 `trade-pipeline-init`），它会一项一项问你：

| 信息 | 用在哪里 | 必填？ |
|------|----------|--------|
| 公司名（中/英） | 所有单据表头 | 是 |
| 地址 | PI/CI 表头 | 是 |
| 联系人 / 邮箱 / 电话 | 报价单和 PI | 是 |
| 银行信息 | PI 付款信息 | 否（可以后补） |
| 贸易条件 | FOB / CIF / DDP / EXW / CFR | 是 |
| 币种 | USD / CNY / EUR | 是 |
| 装运港 | PI/CI 页脚 | 是 |
| 第一个客户 | 买方信息 | 否（可以先用临时客户 `_new`） |

> 这些信息存在一个叫 `config/config.yaml` 的文件里。YAML 是一种简单的文本格式，用记事本就能打开编辑——长得像购物清单，不需要编程知识。

## 日常使用：直接对 Claude 说

装好插件后，你不用记任何命令，把要做的事用大白话说给 Claude 就行。常见说法：

| 你对 Claude 说 | 它会做什么 |
|---|---|
| 「把这份询价单转成报价单」（附上 Excel） | 解析询价 → 生成报价单（给客户谈价格用） |
| 「客户确认了，回写价格并出 PI/CI/PL」 | 把填好的单价写回订单档案 → 生成形式发票 / 商业发票 / 装箱单 |
| 「这是新客户，先用临时身份出报价单」 | 用临时买家身份生成报价单，客户信息之后再补 |
| 「客户名没匹配上，帮我确认一下」 | 列出候选客户让你选，选完继续生成 |

> **推荐流程**：先出报价单谈价格，客户确认后再回写价格、生成正式单据（PI/CI/PL）。
> 这样报价阶段不用反复重做整套单据。

<details>
<summary>开发者参考：底层命令行（Skill 在背后调用的就是这些）</summary>

```bash
# 阶段一：只生成报价单（给客户谈价格用）
python -m trade_pipeline --input 询价单.xlsx --order 2601 --buyer global_fasteners --quote-only

# 阶段二：客户确认后，回写价格 + 生成 PI / CI / PL
python -m trade_pipeline --price-update output/2601/2601_quotation.xlsx --model output/2601/2601_model.json

# 一次生成全套（加急或 demo 场景）：
python -m trade_pipeline --input 询价单.xlsx --order 2601 --buyer global_fasteners

# 新客户（先用临时身份，之后再补）：
python -m trade_pipeline --input 询价单.xlsx --order 2601 --buyer _new --quote-only

# 系统匹配不到客户名时会停下来生成 review.json，确认后继续：
python -m trade_pipeline --input 询价单.xlsx --order 2601 --confirm output/2601/2601_review.json
```

</details>

### 输出文件

```
output/2601/
├── 2601_rfq.json           # 从询价单提取的数据
├── 2601_model.json         # 订单档案（所有单据从这里生成）
├── 2601_quotation.xlsx     # 报价单
├── 2601_pi.xlsx            # 形式发票
├── 2601_ci.xlsx            # 商业发票
└── 2601_pl.xlsx            # 装箱单
```

</details>

---

<details>
<summary><b>技术细节（给开发者和技术评估者看的）</b></summary>

## 架构

```mermaid
graph TD
    A["Excel 询价单"] --> B["提取器<br/>excel_extractor"]
    B --> C["理解层<br/>规则 / LLM 解析"]
    C --> D["组装器<br/>buyer 匹配 + 实体解析"]
    D --> E["OrderModel<br/>唯一数据源"]

    E --> F["报价单 Writer"]
    E --> G["PI Writer"]
    E --> H["CI Writer"]
    E --> I["PL Writer"]

    E -.-> N["验证层"]
    N -.- N1["BuyerMatchError → review.json 硬阻断"]
    N -.- N2["UUID 锚点价格回写 — 行序无关"]

    style E fill:#1F3864,color:#fff,stroke:#1F3864
    style N fill:#f5f5f5,stroke:#999
```

### 8 步管线

| 步骤 | 模块 | 功能 |
|------|------|------|
| 1 | `extractors/excel_extractor.py` | 自动识别 Excel 格式，选最佳 Sheet，提取数据 |
| 2 | `understanding/llm_parser.py` | 解析为结构化数据（规则模式或 Claude API + L1/L2 缓存） |
| 3 | `understanding/canonicalizer.py` | 标准化：DIN/ISO/GB 规范、中英翻译、分组 |
| 4 | `understanding/assembler.py` | Buyer 多级匹配 + OrderModel 组装 |
| 5 | `writers/quote_writer.py` | 报价单 + 隐藏 UUID 列 |
| 6 | `writers/pi_writer.py` | 形式发票 |
| 7 | `writers/ci_writer.py` | 商业发票 + SAY 大写金额 |
| 8 | `writers/pl_writer.py` | 装箱单（Lite 内置 / Full 接私有引擎） |

### 关键设计决策

1. **OrderModel 唯一数据源** — 所有 Writer 只从 OrderModel 读数据，不允许重新解析 Excel。改一处数据，四份单据联动。

2. **UUID 锚点价格回写** — 报价单每行藏一个 UUID。用户插入行、调整顺序后回写价格，系统通过 UUID 精确定位，不会错位。

3. **买家匹配失败 = 硬阻断** — 四级匹配（法定名→别名→子串→模糊）全部未命中时，管线停止并生成 `review.json`。不猜测、不跳过。

4. **双模式解析 + 两级缓存** — 规则优先（快、免费），LLM 兜底（复杂格式）。L1 文件哈希 + L2 内容哈希 + prompt 版本，改了 prompt 自动失效。

5. **三种计价模式** — CNY/MPCS、USD/PC、USD/TON，从 Excel 列头自动检测。

6. **两阶段业务流程** — `--quote-only` 先生成报价单（谈判用），`--price-update` 确认后再生成 PI/CI/PL（正式单据）。

### 运行测试

推荐使用 Python 3.12；仓库包含 `.python-version`，pyenv / uv 用户会自动识别。

```bash
py -3.12 -m pip install -e ".[test]"
py -3.12 -m pytest tests -q
py -3.12 -m ruff check trade_pipeline tests
```

### 设计文档

- [Gate Pattern](docs/gate-pattern.md) — AI 操作的三级门控：哪些自动执行、哪些要问人、哪些绝不能做
- [Output Verification](docs/output-verification.md) — AI 生成的文档怎么验证：逐字段校验、OCR 比对、人工抽检
- [LLM Wiki Pattern](docs/llm-wiki-pattern.md) — 怎么用 AI 把零散的业务知识整理成可复用的知识库

### 技术栈

- **Python 3.12** + openpyxl + PyYAML
- **Claude API**（可选，用于 LLM 解析模式）
- **Claude Code**（开发环境，通过 MCP 协议协作构建）

</details>

---

## 这个工具是怎么做出来的

我不是专业程序员，是一家制造业工厂的的外贸业务人员,更准确的说，是所谓的厂二代，受限于所能获得的资源，很需要强力的助手类工具AGENT。

这个工具存在的原因很简单：**我每周花好几个小时手动做贸易单据，做烦了。** Claude Code 帮我把这些年积累的业务经验变成了可运行的自动化系统。

举个例子：第一版的价格回写功能用的是行号——第 3 行的价格写回第 3 行。技术上完全正确。直到有一天，一个客户在报价单里插了几行分组标题，我跑回写——所有价格全错位了，PI 也跟着错。

我把这个 bug 告诉 Claude，它的第一反应是"解析时排除标题行"。我说不行——客户怎么编辑 Excel 是不可预测的。我们讨论了三轮，最后我提出"每行能不能藏一个隐形身份证？" Claude 实现了 UUID 隐藏列方案。

**这种设计不会出现在编程教程里，因为它来自真实的生产 bug。**

> AI 编码工具在你有深度领域知识时最强大——我非常清楚 PI 应该长什么样，因为我手动做过几百份。

---

## 你的数据在哪里

所有客户信息、订单数据、生成的单据**都存在你自己的电脑上**，不会上传到任何服务器。

| 文件 | 存什么 |
|------|--------|
| `config/config.yaml` | 你的公司信息、客户信息、贸易条件（用记事本就能改） |
| `output/订单号/` | 每笔订单的档案和生成的全套单据 |

这意味着：
- ✅ 数据完全由你掌控
- ✅ 可以用 Git 追溯每次修改记录
- ⚠️ 需要你自己备份（建议定期复制到移动硬盘或加密云盘）

---

## 许可证

MIT — 免费使用，可以自由修改。

---

<p align="center">
  <b>遇到问题？</b><br>
  <a href="https://github.com/Dangooy/trade-pipeline-skill/issues">提一个 Issue</a>（不需要技术背景，写下你看到什么、期望什么即可）
</p>
