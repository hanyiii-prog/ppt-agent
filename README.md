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

这样可以做到：

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

读取已有 PPT 后，不只是复制颜色，而是提取其“设计 DNA”，包括：

- 页面尺寸
- 字体体系
- 色彩体系
- Logo 与品牌元素
- 标题层级
- 页眉 / 页脚
- 页面布局
- 间距与留白
- 卡片与组件
- 表格与图表
- 图片规则
- 页面类型
- 信息密度
- 视觉层级

最终形成可以复用的模板规范，而不是简单截图。

### 3. Story Architect：先讲清楚，再做 PPT

PPT Agent 不应该从“画页面”开始，而应该先理解：

```text
用户是谁？
   ↓
为什么要看？
   ↓
需要得出什么结论？
   ↓
核心证据是什么？
   ↓
这些证据应该如何组织？
   ↓
最终需要多少页面？
```

### 4. Universal IR：与模型和 Agent 解耦

项目核心使用统一的 Presentation IR。

因此核心能力不绑定：

- GPT
- Claude
- Kimi
- DeepSeek
- Qwen
- 其他模型

也不绑定：

- ChatGPT
- Codex
- WorkBuddy
- 豆包工作
- Claude Code
- 其他 Agent Host

只要实现 Adapter，就可以调用同一套 PPT Agent Core。

### 5. Visual QA：生成后必须检查

生成 PPT 后自动渲染页面，并检查：

- 内容溢出
- 元素重叠
- 页面越界
- 字体可读性
- 信息密度
- 留白
- 视觉层级
- 页面一致性
- 图表完整性
- 模板一致性
- 页面之间的重复与节奏

### 6. Repair Loop：发现问题自动修复

PPT Agent 的目标不是“一次生成正确”，而是：

```text
Generate
   ↓
Render
   ↓
Critic
   ↓
发现问题
   ↓
Repair
   ↓
Rebuild
   ↓
Render
   ↓
Recheck
```

直到通过质量 Gate，或者达到最大迭代次数。

### 7. Evidence / Fact Lock：重要数据可追溯

对于数字、指标、结论等重要内容，可以建立来源映射：

```text
PPT 第 3 页
  KPI：82.3%
       ↓
Fact Registry
       ↓
源 Markdown / Word / PDF / PPTX
       ↓
具体来源位置
```

如果生成结果与事实源不一致，可以让构建直接失败，而不是悄悄输出错误数据。

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
             ┌────────────┼────────────┐
             ▼            ▼            ▼
        Native PPTX   Visual Engine   Office
          Engine       HTML/SVG      Engine
             │            │            │
             └────────────┼────────────┘
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
├── core/          # Agent 核心编排与智能能力
├── ir/            # Universal Presentation IR
├── engines/       # PPTX / Visual / Office 渲染引擎
├── intelligence/  # Template DNA / Story / Style 等
├── qa/             # 内容、几何、视觉、证据 QA
├── repair/         # 自动修复
├── adapters/       # 不同 Agent 平台适配器
├── skills/         # 可移植 Skill
├── templates/      # 模板与设计规范
├── examples/       # 示例项目
├── benchmarks/     # Benchmark 与对比测试
├── tests/          # 自动化测试
├── scripts/        # 构建与开发脚本
├── docs/           # 技术文档
└── .github/        # GitHub Actions / Issue / PR 配置
```

## 跨 Agent 平台

PPT Agent 从架构上就不是为某一个平台定制的。

未来目标包括：

| Agent / 平台 | 支持方向 |
|---|---|
| ChatGPT | Adapter |
| Codex | Adapter |
| WorkBuddy | Adapter |
| 豆包工作 | Adapter |
| Claude / Claude Code | Adapter |
| 其他 Agent | Generic Adapter |

核心原则是：

> **Agent 是入口，PPT Agent Core 才是能力本体。**

因此即使未来换模型、换 Agent、换平台，核心代码仍然可以复用。

## 渲染路线

项目计划支持多种生成路线：

### Native PPTX Engine

用于生成真正可编辑的 PowerPoint：

- PptxGenJS
- python-pptx
- OOXML

### Visual Engine

用于快速探索视觉方案：

- HTML
- CSS
- SVG
- Browser rendering
- Slide-oriented web rendering

### Office Engine

在具备 PowerPoint 环境时，可以进一步利用：

- PowerPoint COM
- Office.js
- PowerPoint 原生能力

三种路线不是互相替代，而是根据任务和环境进行路由。

## Roadmap

### V0.1 — Foundation

- Core architecture
- Universal IR
- CLI skeleton
- Portable Skill contract
- GitHub CI foundation

### V0.2 — Template Intelligence

- PPTX inspection
- Template DNA extraction
- Layout grammar
- Style routing

### V0.3 — Generation & QA

- Native PPTX renderer
- Render pipeline
- Geometry QA
- Visual QA
- Basic repair loop

### V0.4 — Evidence

- Fact Registry
- Provenance
- Fact Lock
- Evidence validation

### V0.5 — Visual Intelligence

- Visual Critic
- Quality scoring
- Automatic repair
- Page-level iterative optimization

### V0.6 — Agent Infrastructure

- MCP server
- Generic Agent Adapter
- Capability detection

### V0.7 — Platform Adapters

- Codex
- WorkBuddy
- 豆包工作
- Claude

### V1.0 — PPT Agent

形成稳定、可移植、可持续升级的通用 PPT Agent 平台。

## Benchmark

项目将建立真实 Benchmark，而不是只用“看起来不错”作为评价标准。

第一套 Benchmark 将用于测试：

> **天津市口腔医院信息化项目 PPT / Markdown → PPT Agent 输出**

并与其他 AI PPT 生成方案进行对比。

重点评价：

- 内容完整性
- 信息压缩能力
- 故事逻辑
- 模板还原
- 视觉质量
- 页面一致性
- 数据准确性
- 图表质量
- 可编辑性
- 自动修复能力
- 生成稳定性
- Agent 可移植性

## 开源策略

PPT Agent 的核心架构计划采用开源模式。

具体采用 **MIT、Apache-2.0 或其他合适许可证**，将在完成依赖与商业模式审查后正式确定。

在许可证正式确定前，请不要将当前仓库视为已经完成最终开源授权声明。

同时，项目会尊重所有第三方项目、模板、字体、图片、图标和代码的原有许可证。

## 开发原则

### 1. Fix source, then rebuild

不要直接对最终 PPTX 做不可追踪的人工补丁。

应该：

```text
修改源 / IR / 设计规则
          ↓
       重新构建
          ↓
       重新 QA
```

### 2. Quality Gate

没有通过质量检查的 PPT，不应该直接标记为最终交付物。

### 3. Reproducible Build

相同输入、版本和配置应该尽可能得到可重复的构建结果。

### 4. Model Agnostic

模型可以替换，核心架构不应该被模型绑死。

### 5. Agent Agnostic

Agent 平台可以替换，PPT 能力不应该被平台绑死。

## 当前状态

当前仓库处于 **V0.1 Foundation** 阶段。

接下来将逐步实现：

```text
PPTX Analyzer
      ↓
Template DNA
      ↓
Content Intelligence
      ↓
Story Architect
      ↓
Slide Planner
      ↓
Universal IR
      ↓
Native PPTX Engine
      ↓
Render
      ↓
Visual Critic
      ↓
Repair Agent
      ↓
Final PPTX
```

## English

PPT Agent is a universal, agent-native presentation engineering framework.

Its goal is not merely to generate a `.pptx`, but to provide a reusable, verifiable and portable pipeline for:

`source analysis → story architecture → slide planning → visual design → native PPTX rendering → visual QA → automatic repair`

The core architecture is model-agnostic and agent-host-agnostic. It is designed to support different LLMs, agent hosts, rendering engines and Office environments through explicit adapters.

## License

The final open-source license has not yet been selected. MIT, Apache-2.0 or another appropriate license will be evaluated before the first formal public release.
