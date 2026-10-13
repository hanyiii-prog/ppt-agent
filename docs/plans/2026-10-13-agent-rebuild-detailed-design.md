# PPT Agent 重构详细设计

## 0. 文档信息

- 文档状态：待实现设计
- 目标版本：PPT Agent 3.0
- 适用范围：通用演示文稿 Agent，不绑定医院、政府、商业或其他单一专业
- 参考对象：
  - 用户提供的 `pptd.md`
  - `open-kimi-ppt-skill` 的反向工程思路和设计系统组织方式
  - 当前仓库已有的 Template DNA、CloneShell、Universal IR、渲染器和质量门禁
  - 天津市口腔医院案例，仅作为回归样例，不作为业务规则来源

本文档的目标是让刚接手项目的开发者能够明确：

1. 哪些现有代码必须保留。
2. 哪些现有代码只能作为兼容或兜底。
3. 哪些代码需要重构。
4. 需要增加哪些模块和数据契约。
5. 什么工作交给大模型，什么工作必须由 Agent 规则保证。
6. 如何从输入资料得到可编辑 PPTX。
7. 如何测试代码质量、内容质量和最终视觉质量。

---

## 1. 重构结论

当前 Agent 的主要问题不是缺少更多 `page_kits`，而是上层流程错误：

```text
当前流程：
Markdown → 分页 → 固定 archetype → page_kits → PPTX

目标流程：
多源资料 → 资料理解 → 汇报简报 → PPT 大纲
→ 逐页内容规格 → 模板选择/模板分析
→ 页面构图编译 → Page Design IR
→ 可编辑 PPTX → 渲染审查 → 修复
```

重构后遵循以下原则：

1. 先确定“这一页要让听众理解什么”，再决定页面长什么样。
2. 大模型负责语义理解、叙事判断、内容改写和视觉意图表达。
3. Agent 规则负责事实一致性、来源追溯、结构约束、模板继承、尺寸约束和可编辑性。
4. 页面类型是候选能力，不是固定目录。没有对应内容关系时，不生成对应页面。
5. 用户提供模板时优先继承用户模板。
6. 用户没有提供模板时，使用 Agent 自带的内置模板库。
7. 内置模板继承反向工程中的设计系统思想，但重新实现代码、文档、图形和资源，避免直接复制上游资产。
8. PPTX 是构建产物，真正的源文件是中间表示和构建清单。
9. 所有视觉修复都修改源规格后重新构建，不直接对最终 PPTX 做不可追踪的补丁。
10. 没有视觉模型时可以降级，但必须明确报告视觉审查能力下降。

---

## 2. 现有代码盘点

### 2.1 必须保留并继续使用

以下模块已经解决了底层工程问题，不应因为上层重构而推倒重来：

| 模块 | 保留原因 | 重构后的角色 |
|---|---|---|
| `src/ppt_agent/content_ir.py` | 已有格式无关的内容块模型 | 作为 SourcePack 的基础内容结构 |
| `src/ppt_agent/markdown.py` | Markdown 解析稳定 | 作为一种输入适配器 |
| `src/ppt_agent/template.py` | 已能提取 PPTX Template DNA | 作为用户模板分析入口 |
| `src/ppt_agent/page_dna.py` | 有逐页、逐层的模板 DNA | 作为页面家族和槽位分析输入 |
| `src/ppt_agent/clone_shell.py` | 能继承用户模板装饰 | 作为高保真用户模板渲染路线 |
| `src/ppt_agent/clone_build.py` | 已有数据驱动的克隆构建入口 | 改造为 Page Design IR 的一种渲染后端 |
| `src/ppt_agent/ir.py` | Universal IR 是现有稳定渲染契约 | 继续作为渲染器输入 |
| `src/ppt_agent/dna_to_ir.py` | 能把模板 DNA 转为 IR | 继续支持模板预览和结构分析 |
| `src/ppt_agent/renderers/` | 已有 PPTX 和 HTML 渲染器 | 继续使用同一份布局结果 |
| `src/ppt_agent/preview.py` | 无 Office 环境也能生成预览 | 作为视觉 QA 的兜底渲染器 |
| `src/ppt_agent/visual_regression.py` | 已有渲染比较和状态管理 | 继续作为自动视觉门禁 |
| `src/ppt_agent/visual_critic.py` | 已有规则模型和视觉模型接口 | 扩展输入，不更换基本协议 |
| `src/ppt_agent/fact_registry.py` | 已有事实和来源追溯 | 作为内容质量门禁 |
| `src/ppt_agent/delivery.py` | 已有有界修复循环 | 扩展为源规格修复循环 |
| `src/ppt_agent/sdk.py` | CLI、MCP 和 Python 入口统一 | 继续作为对外门面 |
| `src/ppt_agent/mcp/` | 已有 MCP 工具面 | 增加新阶段工具，保留兼容工具 |

### 2.2 只能保留为兼容或兜底

| 模块 | 当前问题 | 重构后的处理 |
|---|---|---|
| `presentation_plan.py` | 主要按字符容量分页，无法承担叙事规划 | 保留为无大模型时的确定性兜底分页器 |
| `content_analyzer.py` | 只有浅层规则分析 | 保留规则能力，增加大模型增强入口 |
| `page_archetype.py` | 把内容决策过早绑定到固定页面名称 | 降级为视觉构图候选和兼容转换器 |
| `page_kits.py` | 低层渲染器和上层决策混在一起 | 保留渲染函数，禁止其决定叙事和页面顺序 |
| `design.py` | 适合从主题生成通用 IR，但页面语义较弱 | 作为无模板路线的基础编译器 |
| `storyboard.py` | 当前协议固定了 archetype 集合 | 重构为 Outline/SlideSpec 协议，保留旧协议转换器 |
| `pipeline.py` | 流程逐渐堆叠，分支过多 | 重写编排逻辑，复用底层函数 |

### 2.3 需要新增的模块

```text
src/ppt_agent/
├── source_pack.py
├── evidence_graph.py
├── deck_brief.py
├── outline_planner.py
├── outline_validator.py
├── slide_spec.py
├── slide_author.py
├── content_relations.py
├── template_library.py
├── template_selector.py
├── template_profile.py
├── page_family.py
├── slot_allocator.py
├── page_design_ir.py
├── composition_compiler.py
├── deck_evaluator.py
├── quality_report.py
└── rebuild_pipeline.py
```

新增模块必须保持标准库可导入；重型依赖只能在实际需要时延迟导入。

---

## 3. 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│ User Task                                                   │
│ prompt / audience / objective / page budget / style         │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Source Ingestion                                            │
│ Markdown / PDF / PPTX / HTML / DOCX / image                 │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ SourcePack + EvidenceGraph                                  │
│ facts / entities / numbers / time / relations / provenance   │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ LLM: DeckBrief + Outline                                    │
│ audience / objective / story / page purposes                │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ LLM: SlideSpec                                              │
│ takeaway / content / evidence / visual intent / notes       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Template Resolver                                           │
│ user template DNA OR built-in template catalog              │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Composition Compiler                                        │
│ relation → visual form → family → slots → PageDesignIR      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Renderers                                                   │
│ native PPTX / HTML / preview                                │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Quality Loop                                                │
│ structural QA / fact QA / visual QA / repair / rebuild      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 数据契约

所有阶段都必须有明确的 JSON 可序列化契约。禁止通过函数之间传递无法解释的临时字典。

### 4.1 SourcePack

```json
{
  "schema": "source-pack/v1",
  "title": "源材料标题",
  "sources": [
    {
      "id": "source-001",
      "path": "input/report.md",
      "format": "markdown",
      "priority": "primary",
      "content_hash": "sha256...",
      "blocks": ["block-001", "block-002"]
    }
  ],
  "blocks": [
    {
      "id": "block-001",
      "source_id": "source-001",
      "type": "paragraph",
      "text": "原文内容",
      "location": "line:12-16",
      "facts": ["fact-001"]
    }
  ],
  "metadata": {
    "parser_versions": {},
    "warnings": []
  }
}
```

规则：

- 原始资料不能被大模型覆盖。
- 每个事实必须能够反向定位到一个或多个来源块。
- PDF、HTML 和 PPTX 的视觉内容可以作为参考证据，但不能在无法识别时自动编造。
- 来源优先级由用户输入明确指定；未指定时，原始 Markdown 或用户明确标记的主文件优先。

### 4.2 EvidenceGraph

```json
{
  "schema": "evidence-graph/v1",
  "facts": [
    {
      "id": "fact-001",
      "claim": "项目已完成数据采集模块",
      "source_block_ids": ["block-001"],
      "fact_type": "status",
      "confidence": 0.98,
      "locked": true
    }
  ],
  "entities": [],
  "relations": [
    {
      "id": "relation-001",
      "type": "sequence",
      "from": "fact-001",
      "to": "fact-005",
      "source_block_ids": ["block-001", "block-005"]
    }
  ],
  "conflicts": []
}
```

关系类型采用开放集合。初始实现可以支持：

- `sequence`
- `hierarchy`
- `comparison`
- `causal`
- `part_of`
- `progress`
- `distribution`
- `ownership`
- `correlation`
- `contrast`

这些是内容关系，不是页面类型。新增关系不能自动创建一个同名页面类型。

### 4.3 DeckBrief

```json
{
  "schema": "deck-brief/v1",
  "audience": {
    "name": "汇报对象",
    "knowledge_level": "mixed",
    "decision_power": "high"
  },
  "objective": "本次汇报希望听众理解或决定什么",
  "context": "场景背景",
  "tone": ["formal", "credible"],
  "page_budget": {
    "min": 8,
    "max": 14
  },
  "must_include": ["fact-001"],
  "must_not_invent": true,
  "template_preference": null,
  "visual_constraints": [],
  "source_priority": ["source-001", "source-002"]
}
```

### 4.4 Outline

```json
{
  "schema": "outline/v1",
  "title": "演示文稿标题",
  "story": {
    "opening_question": "听众为什么需要关注",
    "central_thesis": "整份 PPT 的核心结论",
    "closing_action": "希望听众采取的行动"
  },
  "slides": [
    {
      "id": "slide-001",
      "kind": "cover",
      "title": "标题",
      "purpose": "建立主题和汇报关系",
      "takeaway": "",
      "evidence_ids": [],
      "source_block_ids": [],
      "speaker_intent": "开场",
      "visual_intent": "标题型开场"
    }
  ],
  "omissions": [],
  "warnings": []
}
```

要求：

- `purpose` 必须存在。
- 内容页必须有 `takeaway`，除非是纯章节页。
- `evidence_ids` 必须能在 EvidenceGraph 中找到。
- 页数由叙事需要决定，不能由固定页面类型列表决定。
- 可以没有目录、章节、时间线、矩阵、组织结构或其他页面。

### 4.5 SlideSpec

```json
{
  "schema": "slide-spec/v1",
  "id": "slide-004",
  "purpose": "说明目前已经形成完整的数据闭环",
  "takeaway": "数据已覆盖采集、治理、分析和应用四个环节",
  "title": "已形成覆盖全流程的数据闭环",
  "content": {
    "lead": "一句辅助说明",
    "items": [],
    "metrics": [],
    "table": null,
    "chart": null,
    "diagram": null,
    "image_requests": []
  },
  "relations": [
    {
      "type": "sequence",
      "nodes": [],
      "edges": []
    }
  ],
  "visual_intent": {
    "preferred_forms": ["flow", "layered_process"],
    "avoid_forms": ["dense_cards"],
    "density": "standard",
    "emphasis": ["takeaway"]
  },
  "evidence_ids": ["fact-001", "fact-005"],
  "speaker_notes": "",
  "layout_constraints": {
    "min_body_font_pt": 16,
    "max_major_items": 5,
    "allow_split": false
  }
}
```

### 4.6 TemplateProfile

```json
{
  "schema": "template-profile/v1",
  "id": "builtin-executive-briefing",
  "source_kind": "builtin",
  "slide_size": [13.333, 7.5],
  "theme": {
    "colors": {},
    "fonts": {},
    "type_scale": {},
    "spacing": {}
  },
  "page_families": [
    {
      "id": "content-evidence",
      "purpose_tags": ["evidence", "comparison", "data"],
      "visual_forms": ["split", "chart_with_conclusion", "metric_group"],
      "slots": [],
      "density": "standard"
    }
  ],
  "assets": [],
  "quality": {
    "validated": true,
    "render_status": "passed"
  },
  "provenance": {
    "created_by": "ppt-agent",
    "license_status": "internal"
  }
}
```

---

## 5. 大模型和 Agent 规则的职责边界

### 5.1 允许大模型决定的内容

大模型适合处理需要语义判断的工作：

- 判断受众和汇报目的。
- 提炼中心结论。
- 组织叙事顺序。
- 判断哪些事实应该放在一起。
- 将段落改写成适合演示的短句。
- 判断事实之间的内容关系。
- 为每页提出视觉表达意图。
- 选择页面内容的主次。
- 生成讲稿和备注。
- 对渲染截图提出视觉修改建议。

大模型输出必须经过 schema 校验、来源校验和规则审查。

### 5.2 不允许大模型单独决定的内容

以下内容必须由 Agent 规则或编译器控制：

- 事实、数字、日期和引用来源。
- 是否违反用户明确约束。
- 页面是否超出模板安全区。
- 文本是否溢出。
- 元素是否重叠。
- 字体是否低于最小可读字号。
- 页面是否使用了不存在的模板槽位。
- 是否保留模板固定装饰。
- PPTX 是否仍然可编辑。
- 文件是否可以被安全导出。
- 页面数量是否超过硬上限。
- 视觉审查是否真正执行。

大模型可以建议坐标和构图，但最终几何位置由槽位、布局约束和编译器决定。

### 5.3 无大模型时的降级

没有内容模型时：

- 使用 `content_ir`、`content_analyzer` 和 `presentation_plan` 生成保守版本。
- 不声称完成了高质量叙事规划。
- 输出报告标记 `llm: off`。

没有视觉模型时：

- 继续执行结构、几何、溢出、空白页和模板继承检查。
- 使用本地渲染器生成预览。
- 不执行语义级视觉判断。
- 输出报告标记 `visual_model: unavailable`。

---

## 6. 模型调用编排

### 6.1 第一次调用：资料分析

入口：`build_source_pack`

输入：

- 用户任务
- 所有源文件的结构化内容
- 模板分析摘要
- 参考图片或页面缩略图（模型支持视觉时）

输出：

- `DeckBrief`
- `EvidenceGraph`
- `ContentRelations`

约束：

- 不生成 PPT 页面。
- 不生成坐标。
- 不编造源文件没有的数字和结论。
- 每个重要事实必须有来源。

### 6.2 第二次调用：大纲生成

入口：`plan_outline`

输入：

- `DeckBrief`
- `EvidenceGraph`
- 页数约束
- 用户模板能力摘要

输出：

- `Outline`

约束：

- 只生成页面目的、顺序、结论和证据。
- 不直接指定某个固定页面套件。
- 不要求所有页面类型都出现。

### 6.3 第三次调用：大纲审查

入口：`validate_outline_with_model`

输入：

- 原始 `Outline`
- `DeckBrief`
- `EvidenceGraph`

输出：

```json
{
  "passed": false,
  "issues": [
    {
      "type": "repetition",
      "slide_ids": ["slide-003", "slide-004"],
      "severity": "high",
      "suggestion": "合并为一页"
    }
  ]
}
```

程序根据审查结果决定是否再次请求模型修改大纲。

### 6.4 第四次调用：逐页写作

入口：`author_slide_specs`

输入：

- 已确认的 `Outline`
- 页面对应证据
- 前后页面摘要
- 模板页面能力

输出：

- 每页一个 `SlideSpec`

约束：

- 内容必须来自证据。
- 标题必须与 `takeaway` 一致。
- 页面不能同时拥有多个同等级主结论。
- 视觉意图使用开放文本和关系类型，不绑定固定 kit。

### 6.5 第五次调用：视觉审查

入口：`review_rendered_deck`

输入：

- 逐页截图
- `SlideSpec`
- `TemplateProfile`
- 结构检查报告

输出：

- 结构化视觉问题
- 优先级
- 建议修改对象

修复只能修改：

- `SlideSpec`
- 页面构图选择
- Page Design IR
- 模板槽位参数

不得直接修改 PPTX 后不回写源规格。

---

## 7. 模板库设计

### 7.1 模板来源

模板来源按以下优先级处理：

1. 用户当前任务提供的模板。
2. Agent 内置的自有模板库。
3. 用户明确授权并导入的模板。
4. 无模板时的通用设计系统。

IMA 不作为运行时依赖，也不是生成过程的必经步骤。

### 7.2 内置模板库目录

建议目录：

```text
src/ppt_agent/assets/template_library/
├── catalog.json
├── templates/
│   ├── formal-enterprise/
│   ├── executive-briefing/
│   ├── work-summary/
│   ├── project-progress/
│   ├── consulting-strategy/
│   ├── business-plan/
│   ├── technology-product/
│   ├── data-analysis/
│   ├── academic-research/
│   ├── training-course/
│   ├── minimal-editorial/
│   └── creative-brand/
└── reports/
```

每套模板至少包含：

```text
template/
├── manifest.json
├── theme.json
├── page_families.json
├── components.json
├── previews/
├── fixtures/
├── quality_report.json
└── assets/
```

### 7.3 继承反向工程内容的边界

可以继承：

- 设计系统的组织方式。
- 主题令牌思想。
- 页面家族思想。
- 页面构图与内容关系的映射方法。
- PPTD 类的页面中间表示思想。
- 先渲染、再检查、再修复的工作流。

不直接复制：

- 上游源码。
- 上游文档原文。
- 原始设计系统文件。
- 原始示例 PPTD 页面。
- 原始图片、插画、图标、Logo 和字体。

内置模板必须使用：

- 自有代码。
- 自有模板命名。
- 自有示例文字。
- 合规字体。
- 自有或已确认授权的图片和图标。

### 7.4 用户模板和内置模板的区别

用户模板只在当前任务中使用：

```text
输入用户模板
→ 分析 Template DNA
→ 生成临时 TemplateProfile
→ 当前任务使用
→ 不自动写入内置模板库
```

只有在用户明确确认具有再分发权、并完成模板资产审核后，才能将其转为内置模板。

---

## 8. 模板选择和页面编译

### 8.1 模板选择评分

`template_selector.py` 根据以下维度评分：

```text
audience_fit
objective_fit
tone_fit
density_fit
relation_support
page_budget_fit
content_type_fit
asset_fit
quality_score
```

模板选择输出：

```json
{
  "template_id": "executive-briefing",
  "score": 0.86,
  "reasons": [
    "适合正式汇报",
    "支持数据和结论页",
    "支持中等信息密度"
  ],
  "fallbacks": ["formal-enterprise", "data-analysis"]
}
```

### 8.2 页面构图决策

页面构图必须经过以下过程：

```text
SlideSpec.relations
→ visual_form_candidates
→ template page families
→ slot compatibility
→ density check
→ selected composition
```

不得直接采用以下方式：

```text
第 1 页 cards_grid
第 2 页 cards_grid
第 3 页 stage_cards
```

### 8.3 Page Design IR

Page Design IR 是从 `SlideSpec` 到 Universal IR 之间的编译层，负责：

- 选择页面家族。
- 为标题、结论、正文、图形和数据分配槽位。
- 解析模板令牌。
- 计算元素尺寸和位置。
- 执行文本容量检查。
- 生成可编辑元素。
- 保存来源和设计决策。

编译结果必须保留：

```json
{
  "page_id": "slide-004",
  "template_family": "content-evidence",
  "composition": "flow-with-conclusion",
  "source_slide_spec": "slide-004",
  "elements": [],
  "warnings": []
}
```

---

## 9. 现有模块的具体改造任务

### 9.1 `storyboard.py`

需要改造：

- 去除固定 archetype 作为必填字段。
- 增加 `purpose`、`takeaway`、`relations`、`evidence_ids`。
- 支持 Outline 到 SlideSpec 的分阶段流程。
- 保留旧 JSON 输入的兼容转换。
- 修复逻辑不能改变来源内容和事实。

完成后的效果：

- 模型先规划大纲。
- 页面结构不再由固定 archetype 列表决定。
- 每页都有明确目的和证据。

### 9.2 `presentation_plan.py`

需要保留：

- 无模型时的保守分页。
- 页数计算和容量基础函数。

需要移除其核心职责：

- 不再承担主要叙事规划。
- 不再用字符数决定全部页面。
- 不再把表格和段落简单按顺序堆叠。

### 9.3 `page_archetype.py`

需要改造成：

```text
visual_form registry
```

每个视觉形式只描述：

- 需要的输入关系。
- 可接受的元素数量。
- 适合的密度。
- 支持的模板槽位。
- 对应的渲染器。

不负责决定：

- 整套 PPT 的顺序。
- 页面是否必须出现。
- 页面标题和内容。

### 9.4 `page_kits.py`

继续保留已有渲染器，但统一输入为 Page Design IR 或规范化的组件数据。

每个 kit 必须：

- 有明确参数契约。
- 不修改来源事实。
- 不自动改变页面结论。
- 返回结构化 warnings。
- 能进行单元测试和独立渲染测试。

### 9.5 `pipeline.py`

建议重写为阶段编排器：

```python
source_pack = ingest_sources(...)
brief, evidence = understand_sources(source_pack, llm=...)
outline = plan_outline(brief, evidence, llm=...)
validate_outline(outline, brief, evidence)
slide_specs = author_slides(outline, evidence, llm=...)
template = resolve_template(brief, slide_specs, user_template=...)
design_ir = compile_pages(slide_specs, template)
artifact = render(design_ir)
quality = evaluate(artifact, source_pack, template)
artifact = repair_and_rebuild(...)
```

每个阶段都应落盘 JSON，方便调试和复现。

### 9.6 `sdk.py`、CLI、MCP

新增阶段工具：

```text
analyze-sources
plan-outline
validate-outline
author-slides
list-builtin-templates
select-template
compile-page-design
evaluate-deck
```

现有 `build` 继续保留，但内部改为调用新编排器。

---

## 10. 生成过程的落盘文件

每次构建都应生成如下工作目录：

```text
workspace/
├── source-pack.json
├── evidence-graph.json
├── deck-brief.json
├── outline.json
├── outline-review.json
├── slide-specs.json
├── template-profile.json
├── composition-plan.json
├── page-design-ir.json
├── deck.pptx
├── preview/
│   ├── slide-0001.png
│   └── ...
├── quality/
│   ├── structural.json
│   ├── facts.json
│   ├── visual.json
│   └── final-report.json
└── manifest.json
```

任何最终问题都必须能够追溯到：

```text
PPTX 元素
→ Page Design IR
→ SlideSpec
→ Outline
→ EvidenceGraph
→ SourcePack
→ 原始文件
```

---

## 11. 测试策略

### 11.1 代码质量测试

每次代码修改必须至少通过：

```text
python -m compileall src
pytest -q
```

此外检查：

- 标准库环境可以导入 `ppt_agent`。
- 所有新 schema 都能序列化和反序列化。
- 错误输入能得到明确异常。
- 大模型不可用时不会出现未声明的假成功。
- 新模块不产生循环依赖。
- 现有 CLI、MCP 和 Python API 仍能调用。

### 11.2 数据契约测试

为每种中间对象增加：

- 最小合法样例。
- 缺少必填字段样例。
- 未知来源 ID 样例。
- 重复来源样例。
- 超出页数样例。
- 模型返回 Markdown 围栏样例。
- 模型返回额外字段样例。
- 事实冲突样例。

测试重点：

- 不能静默丢失来源块。
- 不能接受不存在的证据。
- 不能接受没有目的的内容页。
- 不能让模型覆盖锁定事实。

### 11.3 模型调用测试

使用固定的 fake LLM 响应测试：

- 正常大纲。
- 不完整大纲。
- 违反页数限制。
- 编造数字。
- 使用不存在页面类型。
- 重复页面。
- 无视觉模型。
- 视觉模型返回非法 JSON。

模型测试不依赖真实 API Key，必须可离线运行。

### 11.4 模板库测试

每套内置模板必须自动检查：

- `manifest.json` 合法。
- 主题令牌完整。
- 页面家族至少有封面、内容和收尾能力。
- 每个槽位有尺寸和安全边界。
- 所有引用资源存在。
- 字体配置可解析。
- 预览图可生成。
- 测试内容可编译。
- 生成 PPTX 可编辑。
- 无越界、空页和文字溢出。

模板库不能只测试 JSON 能否读取，必须实际渲染。

### 11.5 内容质量测试

对每个测试案例检查：

```text
事实覆盖率
事实正确率
证据可追溯率
大纲页面目的完整率
页面结论完整率
来源遗漏数
新增未证实事实数
重复页面数
```

建议最低标准：

```text
事实覆盖率 ≥ 95%
证据可追溯率 = 100%
新增未证实事实 = 0
没有结论的内容页 = 0
```

### 11.6 版式和结构测试

对最终 PPTX 和 Page Design IR 检查：

- 页面是否越界。
- 文本是否溢出。
- 元素是否重叠。
- 是否有空文本框。
- 是否有重复标题。
- 是否有过小字体。
- 表格是否可读。
- 图表是否缺少数据。
- 页面是否超过最大密度。
- 模板固定装饰是否被重复绘制。

### 11.7 视觉质量测试

每个真实案例都必须：

1. 生成 PPTX。
2. 渲染全部页面为 PNG。
3. 生成 contact sheet。
4. 运行确定性视觉检查。
5. 有视觉模型时运行模型审查。
6. 记录每次修复前后的评分。

视觉评分至少包含：

```text
信息层级
可读性
页面密度
留白质量
构图完整性
模板一致性
跨页节奏
图示清晰度
文字和图形平衡
```

### 11.8 回归案例

必须至少建立以下案例：

1. 天津口腔医院案例。
2. 纯文字汇报。
3. 数据分析报告。
4. 项目进度汇报。
5. 学术答辩。
6. 商业方案。
7. 培训课程。
8. 含多张表格的报告。
9. 没有用户模板的案例。
10. 用户提供自定义模板的案例。

天津案例只能验证通用能力，不能把医院术语、页面顺序或专业规则写进代码。

---

## 12. 输出物质量验收

### 12.1 交付门槛

最终 PPT 只有同时满足以下条件才算通过：

- 文件可以打开。
- 页面数量符合大纲。
- 所有必需事实存在。
- 所有重要事实可追溯。
- 没有未声明的新增事实。
- 没有空页。
- 没有严重溢出或遮挡。
- 页面可编辑。
- 模板继承检查通过。
- 渲染成功。
- 视觉检查已执行或明确标记降级。

### 12.2 质量报告

`final-report.json` 至少包含：

```json
{
  "status": "passed",
  "model": {
    "content": "used",
    "vision": "unavailable"
  },
  "template": {
    "id": "builtin-executive-briefing",
    "source": "builtin",
    "score": 0.86
  },
  "content_quality": {},
  "structural_quality": {},
  "visual_quality": {},
  "degradations": [],
  "repairs": [],
  "artifacts": {}
}
```

禁止只返回“生成成功”。必须告诉调用方哪些检查真实执行、哪些没有执行。

---

## 13. 实施顺序

### 阶段一：稳定契约

目标：

- 新增 SourcePack、EvidenceGraph、DeckBrief、Outline、SlideSpec、TemplateProfile。
- 为所有对象增加 schema 校验和 JSON 测试。

验收：

- 可以离线构造并序列化完整中间流程。
- 不涉及 PPTX 生成。

### 阶段二：大纲和逐页内容

目标：

- 实现模型调用适配。
- 生成 DeckBrief。
- 生成并审查 Outline。
- 生成 SlideSpec。

验收：

- 天津案例可以生成有明确页面目的的大纲。
- 内容页都有结论和来源。
- 旧模型不可用时可回退。

### 阶段三：内置模板库

目标：

- 建立模板目录和模板 manifest。
- 重新实现第一批设计系统。
- 每套模板有页面家族、槽位、预览和测试案例。

验收：

- 不提供用户模板也能生成多种风格。
- 模板选择有可解释理由。
- 不依赖 IMA 或远程模板下载。

### 阶段四：页面编译

目标：

- 实现 SlideSpec → Page Design IR。
- 复用现有 Universal IR 和渲染器。
- 接入 page_kits 作为底层组件。

验收：

- 页面构图由内容关系和模板能力共同决定。
- 不再出现所有内容都变成卡片的情况。

### 阶段五：用户模板路线

目标：

- 接入现有 Template DNA 和 CloneShell。
- 将用户模板转换为临时 TemplateProfile。
- 优先继承用户模板装饰和页面构图。

验收：

- 模板装饰不被重复绘制。
- 模板结构门禁和视觉门禁都能执行。

### 阶段六：视觉质量闭环

目标：

- 接入视觉模型。
- 生成结构化视觉问题。
- 修改 SlideSpec 或 Page Design IR 后重新构建。

验收：

- 视觉修复不会直接修改不可追踪的 PPTX。
- 修复次数有上限。
- 出现振荡或无效修复时明确停止。

### 阶段七：全量回归和发布

目标：

- 运行全部代码测试。
- 运行所有案例。
- 生成 Kimi 对比报告。
- 检查模板资产和依赖。

验收：

- 代码测试通过。
- 所有模板通过独立渲染检查。
- 关键案例的内容、结构和视觉指标达到设定阈值。

---

## 14. 开发者执行规则

接手开发时必须遵守：

1. 不要直接在 `page_kits.py` 中添加业务判断。
2. 不要在模板库中写医院、项目或单一行业专用逻辑。
3. 不要用字符数量单独决定页面分页。
4. 不要把所有页面强制映射到固定 archetype。
5. 不要让模型直接生成未经校验的 PPTX 坐标。
6. 不要绕过 EvidenceGraph 修改事实。
7. 不要直接修改最终 PPTX 作为长期修复。
8. 不要在没有视觉审查时报告“视觉质量通过”。
9. 不要把用户提供的模板自动加入内置模板库。
10. 不要将第三方代码、文档和素材原样复制进内置模板库。
11. 每增加一种视觉形式，都必须增加输入契约、渲染测试和视觉 fixture。
12. 每增加一套模板，都必须增加 manifest、预览、测试案例和质量报告。

---

## 15. 完成后的预期效果

### 没有用户模板时

```text
用户提供资料和任务
→ Agent 生成汇报大纲
→ Agent 自动选择内置模板
→ 按内容关系选择页面构图
→ 生成可编辑 PPTX
→ 渲染和质检
```

不会退化成单一蓝色主题，也不会把所有页面做成卡片。

### 有用户模板时

```text
用户模板
→ 提取真实模板结构
→ 继承装饰、字体、色彩和页面节奏
→ 按模板真实槽位填入内容
→ 通过模板继承和视觉门禁
```

### 模型不可用时

```text
规则解析资料
→ 保守生成大纲和页面
→ 使用内置模板或用户模板
→ 执行结构和几何质检
→ 明确报告语义能力降级
```

### 视觉模型不可用时

```text
生成 PPTX
→ 本地渲染
→ 规则视觉检查
→ 输出“未执行语义视觉审查”的质量报告
```

最终目标不是让代码“可以生成 PPT”，而是让生成过程可解释、可追溯、可测试、可修复，并在没有用户模板时仍然具备稳定的专业视觉能力。

