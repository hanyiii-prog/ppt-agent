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

## 当前版本：V1.1

V1.1 在 V1.0 的稳定平台之上补上了**渲染质量**这一层。

V1.0 打的是地基（契约 / SDK / MCP / Benchmark / 发布），渲染器只保证"管线跑得通"，产出的是裸文本框堆叠；V1.1 引入真正的设计层，让一份 Markdown 大纲直接变成可以拿去讲的 PPT。

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
V1.1 可视化闭环（PPTX → PNG 光栅预览，门禁由"结构检查"升级为"渲染检查"）
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

10 个工具，覆盖能力查询、模板分析、Markdown→IR、IR→PPTX、IR→HTML、IR 质检、PPTX 门禁、事实审计、端到端构建、主机能力画像。传输层是纯标准库实现的换行分隔 JSON-RPC 2.0 —— 引入官方 MCP SDK 会给一个以“核心可移植”为前提的项目增加运行时依赖，而工具宿主真正需要的协议面很小且稳定。

详见 [`docs/mcp.md`](docs/mcp.md)。

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
│   ├── template.py        # PPTX → Template DNA
│   ├── dna_to_ir.py       # Template DNA → IR
│   ├── renderer.py        # 原生可编辑 PPTX（底层实现）
│   ├── renderers/         # 渲染器 SDK：协议 / 注册表 / native / html
│   ├── adapters/          # 适配器 SDK：协议 / 能力检测 / 主机画像
│   ├── mcp/               # MCP stdio server：协议 / 工具 / 服务
│   ├── sdk.py             # 统一门面 PptAgent（CLI / MCP / 集成共用）
│   ├── page_validation.py # 几何 / 空白页门禁（渲染版 + 结构版）
│   ├── visual_critic.py   # 视觉评审规则
│   ├── visual_regression.py # 渲染 + SSIM/MAE 对比 + 栅格器探测
│   ├── preview.py         # PPTX → 逐页 PNG 光栅预览（Pillow 兜底后端）
│   ├── fact_registry.py   # 事实登记与溯源校验
│   ├── delivery.py        # 交付门禁 + 有界修复循环
│   ├── benchmark.py       # 可复现 Benchmark 套件
│   ├── release.py         # 发布清单与漂移校验
│   └── cli.py             # 命令行入口
├── benchmarks/        # Benchmark 用例与说明
├── ir/                # Universal Presentation IR JSON Schema
├── schemas/           # 能力描述 / 交付清单 Schema
├── scripts/           # 发布脚本
├── skills/            # 可移植 Skill
├── tests/             # 自动化测试（166 项）
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

# 可复现 Benchmark
ppt-agent benchmark benchmarks/cases -o dist/benchmark-report.json

# MCP server
ppt-agent-mcp --workspace ./sandbox
```

新增命令一览：`build`、`capabilities`、`audit-facts`、`benchmark`、`preview`、`mcp`、`ir-to-html`、`release-manifest`、`release-verify`。

> 语义幻灯片会先经 `design.py` 合成版式（主题驱动），再交给渲染器；已带绝对几何的 IR 直接透传。
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
| [`docs/mcp.md`](docs/mcp.md) | MCP server 协议面、10 个工具、workspace 边界 |
| [`docs/adapters.md`](docs/adapters.md) | 能力模型、声明 vs 实际、协商、主机画像 |
| [`docs/release.md`](docs/release.md) | 发布清单、漂移校验、契约版本变更流程 |
| [`docs/production-quality-loop.md`](docs/production-quality-loop.md) | 生产质量循环 |
| [`benchmarks/README.md`](benchmarks/README.md) | Benchmark 用例与报告解读 |

## 测试

```bash
pytest -q                      # 166 项
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

The core architecture is model-agnostic and agent-host-agnostic. It is designed to support different
LLMs, agent hosts, rendering engines and Office environments through explicit adapters.

## License

The final open-source license has not yet been selected. MIT, Apache-2.0 or another appropriate license will be evaluated before the first formal public release.
