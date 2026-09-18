# PPT Agent

**PPT Agent** 是一个面向 AI Agent 的通用演示文稿工程框架。

它的目标不只是“生成一个 `.pptx` 文件”，而是建立一套可复用、可验证、可迭代、可跨 Agent 平台运行的 PPT 智能生成流水线：

`源文件分析 → 故事架构 → 页面规划 → 视觉设计 → 原生 PPTX 生成 → 视觉 QA → 自动修复`

> **Build presentation like software.**
>
> 像开发软件一样开发 PPT。

## 🌏 中文 / English

- **中文文档：** 当前 README
- **English:** see the English sections below

## 当前版本：V2.0.0（Fidelity Engine GA，main 分支）

V2.0.0 建成 **Fidelity Engine 高保真闭环**——不再满足于“结构相似”，而是把“成品像不像参考”变成可验证、可迭代的工程闭环：

- **设计 DNA 提取**：解析参考 PPT 的页面结构、图层顺序、版式继承、旋转/翻转与真实外框、配色与字体体系，形成可复用的模板规范。
- **元素级匹配与 Diff**：按语义身份逐元素比对参考与成品，区分页面 / 图层 / 几何 / 样式 / 文本 / 媒体 / 继承 / 结构八类差异，用规范化哈希消除噪声。
- **属性级修复**：针对可最小修复的差异，直接在原文件上做精准修补并回验；无法最小修复的差异显式跳过，绝不假装修好。
- **渲染级视觉校验**：自动渲染成品并做区域级视觉比对，关键区域（如 Logo）缺失会被单独拦截，不让整页相似度蒙混过关。
- **迭代修复闭环**：结构 Diff → 修复 → 重提取 → 重 Diff → 渲染 → 视觉门禁，最多数轮；振荡与无效修复自动停止并报告。
- **克隆路线高保真门禁**：验证克隆产物对模板装饰的“继承而非重画”，TOC 指纹在链路末端仍保留。
- **CLI + MCP**：`ppt-agent fidelity extract/diff/audit/repair/validate`；MCP 单入口新增 `fidelity_*` 四件套（共 17 工具）。
- **真实 PPTX 回归**：355 项测试全部基于实际构建的 PPTX 包，覆盖单属性突变矩阵、TOC fixture 与端到端闭环，CI 全绿后才可交付。

V1.10 把**克隆壳路线搬上了 MCP 工具面**——从此一个 server 就是全部入口：`ppt_agent_clone_plan`（模板壳位与按页型 DNA 体检）→ `ppt_agent_clone_build`（JSON 页面计划 → 分壳注入 → 审计，kit 参数即 `page_kits` 签名）→ `ppt_agent_clone_audit`（六类页面门禁）。宿主 Agent 不写一行 Python 就能驱动“装饰字节级继承”的高保真路线；顺带修掉 `quad_cards` 注脚条与第二行卡片重叠的几何冲突（有注脚时网格自动压缩，无注脚保持参考几何）。

V1.9 补上了**目录页与占位符治理**：`toc_page` 套件按参考版几何 1:1 复刻目录页（含近乎透明的装饰大圆）；空占位符被正式判定为“死模板 DNA”——`drop_empty_placeholders()` 删除它，`audit_pages` 的 `stale_placeholder` 检查拦住它。空占位符并不惰性：渲染器会把它回退到版式孪生占位符，于是版式里的骨架文本（`单击此处编辑母版标题样式`）被画到页面顶部。

V1.8 把 Template DNA 升级为**按页型逐层提取**（`template-dna/v0.4`，`page_dna.py`）：封面 / 目录 / 章节 / 内容 / 封底五类页各自一份完整图层栈（母版 → 版式 → 幻灯片统一绘制顺序），并覆盖旋转/翻转与旋转后真实外框、渐变**逐停靠 alpha**、run 级颜色 alpha、图片 `alphaModFix` 与媒体指纹。正是这次升级把“封底丢底图满屏实心蓝、目录装饰圆不透明盖住章节文字、章节横幅被画成竖条”三处缺陷一次抓了出来。

V1.7 让**旋转与翻转成为一等公民**（`set_xfrm` / `rotated_bbox` / `clone_shape`），并确立克隆壳路线的铁律：版式已经绘制的装饰**继承而非重画**——`layout_chrome()` 探测版式装饰，`audit_pages` 的 `doubling` 检查拦截重画。

V1.5–V1.6 沉淀 **page_kits 页面套件**（章节页 / 目录页 / 四方职责卡 / 组织架构图 / 双栏清单 / 推进纪实 / 阶段时间轴 / 2×2 卡 / N 列卡），默认字体统一为思源雅黑。

V1.3–V1.4 开辟**克隆壳路线**并重做调色板：`CloneShell` 按版式分壳、清屏注入、剪枝重排，未触碰的装饰与模板字节级一致；`palette.py` 用**面积加权**（schemeClr 经主题解析）替代字面量计数，模板主色不再被少量硬编码色带偏。

V1.2 补上了**模板闭环**：`build --template 你的模板.pptx` 会从参考 PPT 提取配色、字体与字号阶梯，让设计继承那份 PPT 的视觉身份，而不是套用内置预设。

V1.1 在 V1.0 的稳定平台之上补上了**渲染质量**这一层。

V1.0 打的是地基（契约 / SDK / MCP / Benchmark / 发布），渲染器只保证“管线跑得通”，产出的是裸文本框堆叠；V1.1 引入真正的设计层，让一份 Markdown 大纲直接变成可以拿去讲的 PPT。

```text
V1.0 稳定契约（IR / Adapter / Renderer / Benchmark / Release 五个版本号）
        +
V1.0 渲染器 SDK（Native PPTX 引擎 + HTML 视觉引擎，同一套布局算法）
        +
V1.0 适配器 SDK（能力检测 + 能力协商 + 主机画像）
        +
V1.0 MCP Server（10 个工具，零第三方依赖）
        +
V1.0 Benchmark 套件（确定性 / 门禁 / 时延，可复现）
        +
V1.0 可复现发布流程（哈希清单 + 漂移校验）
        +
V1.1 设计层（主题令牌 + 版式合成器，在 IR 层产出带几何与样式的图元）
        +
V1.1 可视化闭环（PPTX → PNG 光栅预览，门禁由“结构检查”升级为“渲染检查”）
        +
V1.2 模板闭环（Template DNA → 主题令牌，产物继承参考 PPT 的配色与字体）
        +
V1.3–V1.4 克隆壳路线 + 面积加权调色板（CloneShell / palette）
        +
V1.5–V1.6 page_kits 页面套件（职责卡 / 组织架构 / 时间轴 / 目录）
        +
V1.7 旋转一等公民（set_xfrm / rotated_bbox / clone_shape）+ 继承不重画 + doubling 审计
        +
V1.8 按页型逐层 Template DNA（template-dna/v0.4，page_dna）
        +
V1.9 空占位符治理（drop_empty_placeholders / stale_placeholder 审计）
        +
V1.10 克隆壳上 MCP 工具面（clone_plan / clone_build / clone_audit，单入口 13 工具）
        +
V2.0.0 Fidelity Engine 高保真闭环（设计 DNA / 匹配 / 结构 Diff / 属性级修复 / 渲染与区域 Diff / 迭代修复 / 17 工具）
```

## 项目定位

PPT Agent 希望解决传统 AI PPT 工具中的几个核心问题：

- 只会“写内容”，不会真正设计演示逻辑
- 只会套模板，无法理解参考 PPT 的设计语言
- 生成后不检查，出现文字溢出、重叠、错位等问题
- 数据和结论容易被模型改写或编造
- PPT 生成能力被绑定在某一个模型或某一个 Agent 平台
- 修改一个页面后，很难稳定地重新构建整个演示文稿

因此，本项目采用 **Source-first + Universal IR + Template DNA + Visual QA + Repair Loop** 的设计思想。

## 核心能力

### 1. Source-first：源文件优先

PPTX 不是唯一的“源代码”，而是构建产物。

内容、故事线、页面规划和设计规则应该保存在可复现的中间表示（IR）中，然后再生成 PPTX。

```text
源文件 / Markdown / Word / PDF / PPTX
                ↓
             分析
                ↓
        Presentation IR
                ↓
         PPTX Build
                ↓
          Render / QA
```

### 2. Template DNA：理解参考 PPT

读取已有 PPT 后，不只是复制颜色，而是提取其“设计 DNA”，包括页面尺寸、字体体系、色彩体系、Logo 与品牌元素、标题层级、页眉页脚、页面布局、间距留白、卡片组件、表格图表、图片规则、页面类型、信息密度、视觉层级。

最终形成可以复用的模板规范，而不是简单截图。

### 3. Story Architect：先讲清楚，再做 PPT

PPT Agent 不应该从“画页面”开始，而应该先理解：用户是谁 → 为什么要看 → 需要得出什么结论 → 核心证据是什么 → 这些证据应该如何组织 → 最终需要多少页面。

### 4. Universal IR：与模型和 Agent 解耦

项目核心使用统一的 Presentation IR，因此核心能力不绑定任何模型（GPT / Claude / Kimi / DeepSeek / Qwen）也不绑定任何 Agent Host（ChatGPT / Codex / WorkBuddy / 豆包工作 / Claude Code）。

只要实现 Adapter，就可以调用同一套 PPT Agent Core。

### 5. 渲染器 SDK：两条生成路线，一套布局

| 渲染器 | 产物 | 用途 |
|---|---|---|
| `native-pptx` | 可编辑 `.pptx` | 正式交付，保留原生可编辑性 |
| `html` | 自包含可打印 HTML | 快速视觉迭代、宿主无法打开 PPTX 时的预览 |

两个引擎共用 `styling.resolve_layout()` 这一份布局算法。这一点是刻意的：如果两个引擎各自布局，跨引擎比对就失去了意义。

### 6. 设计层：让 IR 变成能用的页面

一份大纲变成 PPT，中间缺的那一环是**版式设计**。V1.1 把这一环独立成一层：

```text
语义幻灯片（purpose + 标题 + 要点）
        ↓  ppt_agent.design（由主题令牌驱动）
带几何与样式的图元（色带 / 圆点 / 装饰线 / 文本块）
        ↓  ppt_agent.styling.resolve_layout
两个渲染器（native-pptx / html）共用同一份结果
```

- **`theme.py`** —— 主题令牌：调色板、字体、字号阶梯、版心与节奏。换主题即换整套视觉，不必碰布局代码。
- **`design.py`** —— 版式合成器：封面 / 目录 / 内容 / 章节 / 结尾五种版式，输出纯 IR，所以两个引擎自动共享同一份设计。
- **已带绝对几何的幻灯片**（Template DNA 注入的那条路）原样放过，不会被重新设计。
- **主题可以从模板推导** —— `theme_from_dna()` 把 Template DNA 的配色、字体与字号阶梯映射成主题令牌，所以 `build --template` 出来的页面复用参考 PPT 的视觉身份。正文墨色只在模板的深色槽与主色同色系时才采信，避免把 Office 默认色板的残留当成设计决策。

设计在 IR 层落地，而不是在两个渲染器里各写一遍——这是跨引擎比对能成立的前提。

### 7. 适配器 SDK：能力检测与协商

核心不假设自己一定能栅格化 PPT。`negotiate()` 把宿主**实际具备**的能力和流水线**希望具备**的能力做匹配，每个缺口都带一条有记录的降级路径：

| 缺失能力 | 降级行为 |
|---|---|
| `render_preview` | 优先 LibreOffice；缺失时退回内置 Pillow 光栅器；两者都没有才降级为结构几何门禁 |
| `shell` | 外部栅格化与 Office 自动化不可用，只走纯 Python 路径 |
| `office_automation` | 使用便携的 python-pptx 渲染器 |
| `browser` | HTML 预览落盘但不自动打开 |
| `network` | 所有输入必须能解析为本地路径 |
| `long_running` | 修复循环与 Benchmark 保持有界 |

只有 `filesystem` 是致命能力。**门禁不会被静默跳过**——返回值永远会说明哪些门禁真正跑了、哪些能力被降级了。

### 8. Visual QA：生成后必须检查

生成 PPT 后自动渲染页面，并检查内容溢出、元素重叠、页面越界、字体可读性、信息密度、留白、视觉层级、页面一致性、图表完整性、模板一致性、页面之间的重复与节奏。

### 9. Repair Loop：发现问题自动修复

```text
Generate → Render → Critic → 发现问题 → Repair → Rebuild → Render → Recheck
```

直到通过质量 Gate，或者达到最大迭代次数。

### 10. Evidence / Fact Lock：重要数据可追溯

对于数字、指标、结论等重要内容，可以建立来源映射。如果生成结果与事实源不一致，可以让构建直接失败，而不是悄悄输出错误数据。

### 11. MCP Server：任何 MCP 宿主都能直接调用

```bash
ppt-agent-mcp --workspace /path/to/sandbox
```

17 个工具，覆盖能力查询、模板分析、Markdown→IR、IR→PPTX、IR→HTML、IR 质检、PPTX 门禁、事实审计、端到端构建、主机能力画像、**克隆壳三件套**（`clone_plan` / `clone_build` / `clone_audit`，见第 12 节——模板高保真复刻从此不需要写 Python），以及 **Fidelity Engine 四件套**（`fidelity_extract` / `diff` / `repair` / `validate`，见第 14 节——结构 + 渲染双门禁的高保真闭环）。传输层是纯标准库实现的换行分隔 JSON-RPC 2.0 —— 引入官方 MCP SDK 会给一个以“核心可移植”为前提的项目增加运行时依赖，而工具宿主真正需要的协议面很小且稳定。

详见 [`docs/mcp.md`](docs/mcp.md)。

### 12. 模板克隆壳路线：装饰继承而非重画

设计层路线（`build`）从零绘制页面，适合“白纸起稿”；但当你手里已经一份模板 PPT，更保真的做法是**克隆壳**：把整份模板复制为可写副本，按版式把幻灯片分类成壳，逐页清屏注入内容，最后剪枝重排——未触碰的装饰（照片、LOGO、自由曲线、渐变）与模板**字节级一致**，不存在“重新渲染的近似”。

```python
from ppt_agent.clone_shell import CloneShell, audit_pages, rebuild_cover

deck = CloneShell("template.pptx")          # 按版式分壳
idx, slide = deck.take("content")           # 取一个内容壳，body 已清屏
# ...注入内容...
deck.finish("out.pptx", order=[0, 2, 3])    # 剪枝 + 重排 + 保存

issues = audit_pages(deck.prs)              # 溢出 / 碰撞 / 空页 / 重复 / 重画 / 空占位符
```

克隆壳内置旋转感知原语，专门处理模板装饰里的旋转、翻转、渐变透明度与自定义几何，确保复刻结果与参考版逐属性一致；并强制“继承而非重画”——模板版式已绘制的装饰直接复用，不重复绘制。

`audit_pages` 是这条路线的质量门禁：`overflow / collision / empty / duplicate / doubling / stale_placeholder` 六类检查，零 issue 才算交付。

### 13. 按页型的 Template DNA

`page_dna.extract_deck_dna()` 把 DNA 提取从“每页一张扁平形状表”升级为**按页型逐层提取**：封面 / 目录 / 章节 / 内容 / 封底五类页各自一份完整图层栈（母版 → 版式 → 幻灯片统一绘制顺序），并覆盖旋转/翻转、渐变透明度、字体与图片等全属性，让“谁盖住谁、继承链是什么”可以直接回答。

老消费者无需改动；`analyze_pptx` 是它的薄包装。

### 14. Fidelity Engine：从“结构相似”到“高保真闭环”（V2.0.0）

Fidelity Engine 把“成品像不像参考”变成可验证的闭环：提取参考 DNA → 元素级匹配 → 结构 Diff → 属性级修复 → 渲染 → 区域视觉 Diff → 迭代修复 → 回归门禁。

```bash
# 提取一页的硬化 OOXML 指纹
ppt-agent fidelity extract ref.pptx --slide 2 -o dna.json

# 单页结构 diff
ppt-agent fidelity diff ref.pptx cand.pptx --slide 3 -o diff.json

# 整册结构门禁
ppt-agent fidelity audit ref.pptx cand.pptx -o gate.json

# 迭代修复
ppt-agent fidelity repair ref.pptx cand.pptx -o repaired.pptx --render

# 结构 + 渲染双门禁验证
ppt-agent fidelity validate ref.pptx repaired.pptx --workspace dist/fidelity
```

核心保证：**渲染器不可用/报错永远不是 visual pass**；`A→B→A` 振荡修复自动停止并报告；不可最小修复的差异显式 skipped，绝不假装修复。

## 整体架构

```text
                         USER
                           │
                           ▼
                    HOST AGENT
             ChatGPT / Codex / WorkBuddy
                   / 豆包工作 / Others
                           │
                           ▼
                    Adapter Layer
                （能力检测 + 能力协商）
                           │
                           ▼
                 ┌──────────────────┐
                 │   PPT Agent Core │
                 │                  │
                 │ Document Analyst │
                 │ Story Architect  │
                 │ Slide Planner    │
                 │ Visual Designer  │
                 │ Orchestrator     │
                 └────────┬─────────┘
                          │
                          ▼
                 Universal PPT IR
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
     Native PPTX Engine        Visual Engine (HTML)
       python-pptx               自包含可打印
             │                         │
             └────────────┬────────────┘
                          ▼
                     Render / QA
                          │
                    ┌─────┴─────┐
                    ▼           ▼
                   PASS        FAIL
                    │           │
                    │        Repair Agent
                    │           │
                    └─────┬─────┘
                          ▼
                     Final PPTX
```

## 仓库结构

```text
ppt-agent/
├── src/ppt_agent/
│   ├── contracts.py       # 稳定版本 + 能力模型 + IR 版本校验 + 协商
│   ├── theme.py           # 主题令牌：调色板 / 字体 / 字号阶梯 / 版心节奏
│   ├── design.py          # 版式合成器：语义幻灯片 → 带几何与样式的 IR 图元
│   ├── styling.py         # 共享样式约定 + 唯一一份布局算法
│   ├── ir.py              # Universal IR 数据模型
│   ├── markdown.py        # Markdown → IR
│   ├── story.py           # Story Architect（叙事大纲 → IR）
│   ├── template.py        # PPTX → Template DNA（analyze_pptx 委托 page_dna）
│   ├── page_dna.py        # 按页型逐层 Template DNA：图层栈 / 旋转 / 透明度
│   ├── fidelity.py        # Fidelity Engine：参考 PPT 硬化指纹提取器
│   ├── fidelity_model.py  # Canonical Fidelity Model：Deck / Slide / Element 三级统一模型
│   ├── fidelity_match.py  # 元素匹配引擎：参考与成品逐元素配对
│   ├── fidelity_diff.py   # 结构 Diff：八类差异 + 规范化哈希
│   ├── fidelity_gate.py   # 整册结构门禁（逐页 + 修复指令）
│   ├── fidelity_repair.py # 修复指令规划（RepairDirective / Repair Plan）
│   ├── fidelity_repair_executor.py  # 属性级修复 + 回验
│   ├── fidelity_pipeline.py         # 迭代修复闭环（振荡检测）
│   ├── fidelity_score.py  # 包级保真度评分
│   ├── palette.py         # 面积加权调色板（schemeClr 经主题解析，区域加权）
│   ├── clone_shell.py     # 模板克隆壳：分壳清屏注入剪枝重排 + 页面审计
│   ├── clone_build.py     # 克隆壳的数据驱动入口 + chrome fidelity gate
│   ├── page_kits.py       # 可复用页面套件：目录 / 章节 / 职责卡 / 组织架构 / 时间轴等
│   ├── dna_to_ir.py       # Template DNA → IR
│   ├── renderer.py        # 原生可编辑 PPTX（底层实现）
│   ├── renderers/         # 渲染器 SDK：协议 / 注册表 / native / html
│   ├── adapters/          # 适配器 SDK：协议 / 能力检测 / 主机画像
│   ├── mcp/               # MCP stdio server：协议 / 工具（17）/ 服务
│   ├── sdk.py             # 统一门面 PptAgent（CLI / MCP / 集成共用）
│   ├── page_validation.py # 几何 / 空白页门禁（渲染版 + 结构版）
│   ├── visual_critic.py   # 视觉评审规则
│   ├── visual_regression.py # 渲染 + 四态状态机 + 区域 Diff + 关键区域门禁
│   ├── preview.py         # PPTX → 逐页 PNG 光栅预览（Pillow 兜底后端）
│   ├── fact_registry.py   # 事实登记与溯源校验
│   ├── delivery.py        # 交付门禁 + 有界修复循环
│   ├── benchmark.py       # 可复现 Benchmark 套件
│   ├── release.py         # 发布清单与漂移校验
│   └── cli.py             # 命令行入口（含 fidelity 五个子命令）
├── benchmarks/        # Benchmark 用例与说明
├── ir/                # Universal Presentation IR JSON Schema
├── schemas/           # 能力描述 / 交付清单 Schema
├── scripts/           # 发布脚本
├── skills/            # 可移植 Skill
├── tests/             # 自动化测试（355 项）
├── docs/              # 技术文档
└── .github/           # GitHub Actions / Issue / PR 配置
```

## 安装与运行

```bash
python -m pip install -e ".[pptx,qa,test]"
```

核心包**不依赖任何第三方库**，`import ppt_agent` 永远成功；`python-pptx` / `Pillow` / `numpy` 由需要它们的模块按需导入。CI 中有一个 `dependency-free-core` 任务专门守这条线。

### 命令行

```bash
# 查看当前宿主能做什么（建议第一步）
ppt-agent capabilities

# Markdown → IR → 可编辑 PPTX + HTML 预览 + 门禁 + 交付清单
ppt-agent build outline.md -o workspace --stem deck

# 同一条命令顺带出逐页 PNG 预览（不装 LibreOffice 也能看）
ppt-agent build outline.md -o workspace --stem deck --preview

# 用你的模板：产物继承该 PPT 的配色、字体与字号阶梯
ppt-agent build outline.md -o workspace --stem deck --template 你的模板.pptx

# 已有 deck 单独出图
ppt-agent preview workspace/deck.pptx -o workspace/preview --dpi 120

# 参考 PPT → Template DNA → IR
ppt-agent pptx-to-ir reference.pptx -o ir.json

# IR → 原生可编辑 PPTX / HTML 预览
ppt-agent ir-to-pptx ir.json -o deck.pptx
ppt-agent ir-to-html ir.json -o deck.html

# 逐页质检
ppt-agent validate-pptx deck.pptx -o qa.json

# 事实审计（未登记的说法会让构建失败）
ppt-agent audit-facts ir.json --facts facts.json

# Fidelity Engine：提取 / 对比 / 门禁 / 修复 / 验证
ppt-agent fidelity extract ref.pptx -o dna.json
ppt-agent fidelity audit ref.pptx cand.pptx -o gate.json
ppt-agent fidelity repair ref.pptx cand.pptx -o repaired.pptx --render
ppt-agent fidelity validate ref.pptx repaired.pptx --workspace dist/fidelity

# 可复现 Benchmark
ppt-agent benchmark benchmarks/cases -o dist/benchmark-report.json

# MCP server
ppt-agent-mcp --workspace ./sandbox
```

新增命令一览：`build`、`capabilities`、`audit-facts`、`benchmark`、`preview`、`mcp`、`ir-to-html`、`release-manifest`、`release-verify`、`fidelity extract/diff/audit/repair/validate`。 `build` 另有 `--template`（模板驱动主题）与 `--preview`（逐页 PNG）两个开关。

> 语义幻灯片会先经 `design.py` 合成版式（主题驱动），再交给渲染器；已带绝对几何的 IR 直接透传。
> 给了 `--template` 时，主题令牌改由模板 DNA 推导（配色 / 字体 / 字号阶梯），内置预设不再参与。
> 渲染器支持文本 / 形状 / 图片 / 表格 / 图表（占位）/ 分组，椭圆图元，绝对坐标与自动流式排版，填充透明度（OOXML `a:alpha`）；渐变暂降级为纯色。两个引擎的已知限制见 [`ROADMAP.md`](ROADMAP.md)。

## Benchmark

项目建立了可复现的 Benchmark，而不是只用“看起来不错”作为评价标准。

`ppt-agent benchmark` 会把每个用例渲染两遍，只有同时满足以下四条才算通过：

1. 两次 IR 完全一致
2. 两次 PPTX 的形状树完全一致（PPTX 会嵌入打包时间戳，所以比对形状树而不是字节）
3. 两次 HTML 完全一致
4. 每一页都通过交付门禁

报告里的路径全部相对于 workspace，不含任何机器相关细节，因此不同宿主的报告可以直接对比。

第一套正式 Benchmark 将用于测试 **天津市口腔医院信息化项目 PPT / Markdown → PPT Agent 输出**，并与其他 AI PPT 生成方案进行对比。

## 开源策略

PPT Agent 的核心架构计划采用开源模式。

具体采用 **MIT、Apache-2.0 或其他合适许可证**，将在完成依赖与商业模式审查后正式确定。

在许可证正式确定前，请不要将当前仓库视为已经完成最终开源授权声明。同时，项目会尊重所有第三方项目、模板、字体、图片、图标和代码的原有许可证。

## 开发原则

### 1. Fix source, then rebuild

不要直接对最终 PPTX 做不可追踪的人工补丁。应该修改源 / IR / 设计规则，然后重新构建、重新 QA。

### 2. Quality Gate

没有通过质量检查的 PPT，不应该直接标记为最终交付物。**门禁降级必须被显式报告，而不是静默跳过。**

### 3. Reproducible Build

相同输入、版本和配置应该尽可能得到可重复的构建结果。三层可复现性都有自动化守门：IR 层（渲染确定性）、流水线层（Benchmark）、发布层（哈希清单）。

### 4. Model Agnostic

模型可以替换，核心架构不应该被模型绑死。

### 5. Agent Agnostic

Agent 平台可以替换，PPT 能力不应该被平台绑死。

## 文档

| 文档 | 内容 |
|---|---|
| [`ROADMAP.md`](ROADMAP.md) | 版本进度、渲染器范围、已知限制、契约兼容策略 |
| [`docs/architecture.md`](docs/architecture.md) | 分层、模块职责、渲染契约、能力降级矩阵 |
| [`docs/mcp.md`](docs/mcp.md) | MCP server 协议面、工具清单、克隆壳三件套、workspace 边界 |
| [`docs/adapters.md`](docs/adapters.md) | 能力模型、声明 vs 实际、协商、主机画像 |
| [`docs/release.md`](docs/release.md) | 发布清单、漂移校验、契约版本变更流程 |
| [`docs/production-quality-loop.md`](docs/production-quality-loop.md) | 生产质量循环 |
| [`benchmarks/README.md`](benchmarks/README.md) | Benchmark 用例与报告解读 |

## 测试

```bash
pytest -q                      # 355 项
ppt-agent benchmark benchmarks/cases -o dist/benchmark-report.json
python scripts/release.py build && python scripts/release.py verify
```

## English

PPT Agent is a universal, agent-native presentation engineering framework.

Its goal is not merely to generate a `.pptx`, but to provide a reusable, verifiable and portable pipeline for:

`source analysis → story architecture → slide planning → visual design → native PPTX rendering → visual QA → automatic repair`

V1.1 keeps the V1.0 stable platform and adds the layer it was missing: a **design layer** that turns
semantic slides into positioned, styled primitives behind a theme token system, plus a self-contained
Pillow rasteriser, so visual gates run in `mode=rendered` even on a machine without LibreOffice.

V1.2 closes the template loop: `build --template ref.pptx` derives the theme tokens from the
reference deck Template DNA — palette, fonts and type scale — so the output carries that deck
visual identity instead of a built-in preset.

V1.3–V1.9 add a second, higher-fidelity production route: the **template clone shell**
(`ppt_agent.clone_shell`) — classify the template's slides into shells by layout, clear and inject
per page, prune and reorder, so untouched photos / logos / freeforms stay byte-identical — plus
**page kits** (`ppt_agent.page_kits`: TOC, chapter divider, responsibility cards, org chart,
timelines), rotation-aware primitives that keep replicas pixel-faithful to the reference, an
**inherit-don't-redraw** chrome rule, and **per-page-kind Template DNA** (`ppt_agent.page_dna`:
cover / toc / section / content / closing layer stacks). Empty placeholders are dropped and audited
(`stale_placeholder`) to avoid leaking layout skeleton text.

V1.10 puts the clone route on the MCP tool surface, so one server is the whole entry point:
`ppt_agent_clone_plan` (shell inventory + per-page-kind DNA), `ppt_agent_clone_build` (a JSON
page plan → one shell per spec, dispatched to the page kits, audited) and
`ppt_agent_clone_audit` (the six-kind page gate). A host agent now drives the
byte-identical-template route without writing Python.

V2.0.0 (Fidelity Engine GA, formerly `v1.11-fidelity-engine`) builds the **Fidelity Engine closed loop** — a verifiable,
iterative pipeline that compares the generated deck against the reference at both structure and
render level, applies targeted repairs, and re-checks until it passes or stalls. CLI:
`ppt-agent fidelity extract|diff|audit|repair|validate`; MCP: four `fidelity_*` tools (17 total).

The core architecture is model-agnostic and agent-host-agnostic. It is designed to support different
LLMs, agent hosts, rendering engines and Office environments through explicit adapters.

## License

The final open-source license has not yet been selected. MIT, Apache-2.0 or another appropriate license will be evaluated before the first formal public release.
