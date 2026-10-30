# Draw to Explore：三 Agent 反馈系统

当前浏览器反馈链路由 Transformation、Evaluation、快速 Tutor 三个 LLM 角色组成，共享稀疏 Learner model。首次提交及真正提交改图后调用 Evaluation；普通对话、hint 和仅解释文字的变化只调用一次 Tutor。有实质学习更新才写入 Learner model，近期六轮对话单独作为短期上下文。

在项目根目录运行：

```bash
python3 -B experiments/open_ended_sketch/app/server.py --port 8765
```

打开 http://127.0.0.1:8765/。模型通过本地环境配置：`EVALUATION_MODEL`、`TRANSFORMATION_MODEL`、`TUTOR_MODEL`；API key 仍从已有 `.env` 读取。正式评估、教师对话和图示转换分别使用独立模块与契约。Python 流程控制器管理阶段、当前问题与 review 回路；Tutor 在当前允许范围内选择教学 move。当前要求见 [FEEDBACK_LOGIC.md](FEEDBACK_LOGIC.md)，完整流程的前后版本和验证见 [流程归档](../../outputs/feedback_full_process_20261027/)，三 Agent 重构记录见 [架构归档](../../outputs/three_agent_refactor_20261027/)。

以下保留独立绘图转换实验的历史结果和 CLI 使用方式。

# 开放式学生绘图 → 可交互对象

使用独立 GPT‑6 API 从图片识别对象、相对位置、分组、文字和关系，再交给通用浏览器编辑器。原始模型 JSON 保存不改，交互操作只改变浏览器中的副本。

## 本次 energy 结果

2026-09-22 已用相同 prompt 实际完成两次 `gpt-6-astra` API 调用：

- [打开结果](results/20260922T035929331824Z/index.html)：pic1 为 12 个对象（含 1 个分组）、9 条关系；pic2 为 17 个对象（含 2 个分组）、5 条关系。
- [查看复核说明](results/20260922T035929331824Z/review.md)：pic2 的 4 条关系含端点/含义歧义，不能把生成成功当成语义确定。
- 浏览器验证涵盖拖动、连线跟随、修改、停用、路径动画、导出、恢复与窄屏布局；两张结果没有脚本错误。
- 合计使用 42,875 tokens。没有重试、换模型或手工修正模型 scene JSON。

## 快速运行

在项目根目录执行。Python 3.9+：

```bash
python3 -m pip install -r experiments/open_ended_sketch/requirements.txt

# 默认读取 data/energy 中的全部 PNG/JPEG/WebP；每图一次请求
python3 experiments/open_ended_sketch/run.py

# 换一个任务：只换图片目录，无须改 prompt 或元件词表
python3 experiments/open_ended_sketch/run.py --input-dir data/your_task

# 也可以指定图片，并提供真实题干作为背景
python3 experiments/open_ended_sketch/run.py \
  --images data/your_task/example.png \
  --task-file data/your_task/task.txt

# 题目有配图时，单独提供题目配图；不要传标准答案图
python3 experiments/open_ended_sketch/run.py \
  --images data/your_task/student_response.png \
  --task-file data/your_task/question.txt \
  --question-image data/your_task/question.png \
  --question-id example-task

# 只准备请求，不访问 API
python3 experiments/open_ended_sketch/run.py --input-dir data/your_task --dry-run
```

`OPENAI_API_KEY` 优先从已有环境变量读取，再依次读取本实验 `.env`、项目根 `.env`、旧 `sketch_to_interactive/.env`。不打印密钥。每张图片单独调用 `gpt-6-astra`，默认 `--profile fast`：low reasoning、原始细节图片、16,000 输出 token 上限、压缩结构。没有自动重试或切换模型。

旧版完整输出可通过 `--profile full` 使用：high reasoning、24,000 token 上限、v1.1 prompt。两种模式均可用 `--effort` 单独覆盖推理强度。输出上限只用于防止无限输出；提速依靠降低推理强度及减少实际生成内容，不依靠截断结果。

每次运行生成 `results/<UTC时间>/index.html`。直接双击打开，不需要服务器。HTML 内嵌输入图片、模型数据和编辑器，不需要 CDN。

## 可迁移的 prompt

当前快速版英文提示词：[`prompts/reconstruct_v1.2_compact.md`](prompts/reconstruct_v1.2_compact.md)，完整输出版本：[`prompts/reconstruct_v1.1.md`](prompts/reconstruct_v1.1.md)。历史两张 energy 图片使用的 v1.0 prompt 保留于 [`prompts/reconstruct.md`](prompts/reconstruct.md) 及当次运行目录中；没有题干、人工对象列表或标准答案输入。

提示词的核心约束：

1. 识别学生实际画出的表示，不替学生解题或修正模型。
2. 让模型自行决定对象类别，适用于概念文字、具象图画和混合表示。
3. 同名但不同位置的概念保持独立；分组只是组织方式，不产生新关系。
4. 每个对象、端点和箭头提供图中依据；不明确时保留空端点和歧义。
5. 同时输出原图定位框及简化矢量笔画，支持并排核对。
6. 区分可编辑表示、图上的有向可达路径和需要额外规则的定量模拟。

快速版 API 输出契约见 `compact.py` 的 `CompactSketch`，随后用 `expand()` 转为 `schema.py` 的统一 `Sketch`。完整模式直接使用 `Sketch`。调用时把匹配的 prompt 作为 `instructions`、学生图作为 `input_image`、可选题干作为 `input_text`，通过相应 `text_format` 要求结构化输出。`reconstruction.py` 统一管理这两套配置。

压缩版保留独立对象、实际文字、笔画、颜色、分组、连线及歧义；精简重复描述与坐标字段。连线中间的箭头必须在原位置分段表示，邻接物体仍应独立可编辑。压缩版不评估定量仿真准备程度，适配器对此明确标记未评估。研究用置信度仍是模型自报值。

## 目前支持的交互

- 独立拖动对象、组合移动分组；附属连线跟随对象。
- 切换模型的简化矢量图和基于模型定位框的原笔迹裁图。
- 选择对象时，在原图高亮对应区域，查看证据、歧义及模型自报置信度。
- 修改对象名称、箭头文字、端点与方向；新增和删除对象/连接。
- 添加或编辑纯文本时，文本框按内容收缩并保持字号，短标签可拖到画布右侧。
- Connect / Edit connection 可选择 Straight、Curved 或 Bent；选中连线后拖动方形中间点调整弧度或折点，圆形端点用于改变起止位置。
- 从选定对象沿显式箭头探索，播放路径动画；停用对象或连接后比较可达性。
- 撤销、恢复模型输出、导出 JSON/SVG、下载人工复核记录。

“原笔迹对象”是矩形裁图，可能包含纸纹或附近笔画，不是像素级分割。名称编辑不会改写原图或原始手写文字；修改后的名称显示在对象旁边。矢量轮廓是近似，不保证逐像素一致。

## 定性探索不是物理仿真

关系探索只计算图上的有向可达性。它不推断缺失的连接，不给物理量赋默认值，不模拟能量守恒、水流或生态变化。箭头可能表示资源流、顺序、关联等不同含义，不能一律视作已确认的因果关系。

有歧义、低置信、推断来源或未确定端点的关系默认排除；用户可在关系面板确认解释。无箭头连接不会自动转成流。分组与其成员之间没有隐含传播边，停用分组也不等于停用所有子对象。

本次适合测试“保留并编辑学生表达”和“探索图中显式路径”。需要定量模拟时，应另外取得学生对机制的解释、变量、单位、参数与方程；即使 schema 标为 equations_visible，本查看器也不会自动执行方程。动态图形或三维几何需扩展对应行为模块，不能仅靠换 prompt 宣称通用物理模拟。

## 可追溯的实验输出

- `*.response.json`：完整模型响应、返回模型、response ID、token 使用。
- `*.scene.json`：通过结构验证的统一场景；快速版由程序从压缩输出展开，未人工修图。
- `*.compact.json`：快速版原始结构化结果。
- `*.timing.json`：API 与本地校验总耗时，以单调时钟测量。
- `*.input_manifest.json`：原图路径、尺寸、SHA256 和题干背景。
- `prompt.md`、`schema.json`、`run_config.json`：本次模型输入契约、配置与 prompt 哈希。
- `render_manifest.json`：渲染器代码哈希，区分模型结果与界面实现。
- `report.json`：逐图成功/失败；生成成功不等同识别正确。
- `*.html`、`index.html`：离线交互页面。

dry-run 会保存包含图片 base64 的请求 JSON，不含密钥。模型拒绝、截断或结构错误时，失败会明确记录；不会用手工场景代替模型输出。

只更新界面、不再次调用模型：

```bash
python3 experiments/open_ended_sketch/render.py experiments/open_ended_sketch/results/<run-id>
```

## 验证

### 对话策略与编辑权限

`app/feedback_policy.py` 统一决定 move、当前问题的思考机会和编辑授权；`app/feedback.py` 校验生成内容后才提交状态。英文 move 定义与少量示例位于 `prompts/feedback_tutor.md`、`prompts/feedback_evaluator.md`、`prompts/feedback_fast_dialogue.md` 和 `prompts/feedback_examples.md`。

2026-10-25 恢复 **I need a hint** 按钮，主动请求之间固定间隔 **2 turns**。一次成功请求后再次点击会提醒还需回答几轮 Dialogue，不发送新请求；成功提交两条普通聊天回复后可再次使用。后端也拦截重复按钮请求，失败请求不扣轮数；原有文字求助和自动 guidance 规则不变。

**Current Guidance policy — 2026-10-28:** Guidance is permitted only after three consecutive incorrect answers on the current issue, an accepted actual **I need a hint** button click, or clearly expressed current frustration. Ordinary uncertainty, inability and conversational requests for hints, examples or explanations receive higher scaffolding through other eligible moves. A previous hint does not authorize later Guidance. This supersedes the earlier broader chat-help eligibility. See [the current system logic](FEEDBACK_LOGIC.md) and [updated editable process figure and policy record](../../outputs/feedback_guidance_gate_20261028/index.html).

- 当前完整路由见 [FEEDBACK_LOGIC.md](FEEDBACK_LOGIC.md)：Highlight 后先检查最重要的问题；有证据的错误用 accuracy check，模糊含义用 revoice/clarify。进入 Support thinking 后，按有证据的认知冲突、可用已有知识联系、推理缺口依次选择 reflection、prior knowledge 或 elaboration，不再轮换 move 标签。
- 同一问题上连续三次有原话证据的未成功回应后，给一个清楚的原则或有限步骤；有推进的成功回应清零。明确求助或表达挫败时及时帮助，已有充分理解时推进 revision。
- 实际修改 review 成功时先具体夸奖，选下一个关键问题后直接进入 Support thinking；失败时直接指出有证据的问题，再用 Support thinking 支持当前问题。无需重跑初始 accuracy/revoice 检查；未改变图稿不能冒充修改成功。
- 学生明确请求 revision 可以开放编辑；系统只有在 revision plan 或 guidance 中给出可见的图稿修改指令时才开放。查看、机制演示、解释和理由追问保持只读，move 名称本身不授权编辑。
- 退出 revision 或提交修改后关闭编辑，并禁用左侧理由输入框；需要补充理由时在聊天框中追问和回答，图稿保持只读。Begin/Exit revision 只改变权限，Show 只重放对应图示。已理解且改对的操作调整无需再问一次 WHY。
- Tutor 可以确认学生当前消息里自己提出的操作想法，但不能增加新动作、方向、数量或目标；这不授权编辑。已有学生箭头和已有对象一样可以作为准确性检查的图示依据，尚未讨论的答案位置仍受保护。
- 有实际未提交的图稿变化、且学生在聊天中要求检查时，界面提示点击 **Review changes**；已退出编辑时先提示 **Begin a revision**。正常 reasoning 和 hint 对话继续基于已提交版本，不会自动提交草稿。

`tests/test_historical_feedback_failures.py` 回放 2026-10-12 Math 案例的三次失败响应。原始 API 均已完成；失败来自本地校验把转述判成新修改指令、以及把已提交箭头判成受保护的答案位置。回放不调用模型，也不改写原始案例记录。

### 本地工作区的案例导出

对话页面的 **Export case HTML** 导出可离线打开的完整案例，包含题目配图、提交图稿、实际消息和各轮对应的 Show 图示。未提交的草稿不会写入展示用 HTML。实现位于 `app/case_export.js`；更新静态路由后须重启 `app/server.py`，否则旧服务可能无法提供新增模块。

更新服务前可用 **Save** 保存完整 JSON 备份。需要保留正在展示的案例时，在停止旧服务后执行：

```bash
python3 -B experiments/open_ended_sketch/app/server.py --port 8765 \
  --resume-case path/to/case.exploration.json
```

`app/case_resume.py` 核对备份与本地最新 session 记录，恢复后台状态，并向第一个加载页面提供一次恢复数据；恢复不调用模型，以只读模式继续。恢复完成后不要再次刷新该页面，除非已保存新的备份并重新提供恢复数据。

### 自动检查

```bash
node experiments/open_ended_sketch/tests/test_graph.cjs
node experiments/open_ended_sketch/tests/browser_check.mjs experiments/open_ended_sketch/results/<run-id>
```

另可运行 `python3 -B experiments/open_ended_sketch/tests/test_schema.py` 检查空端点保留、无效引用、分组循环与非法坐标。

浏览器检查使用独立临时配置的无头 Chrome，验证拖动、连线跟随、改接、停用路径、导出及窄屏显示。可通过 `PLAYWRIGHT_MODULE` 指向自己安装的 Playwright。

软件测试不能代替保真检查：应逐项比对对象、标签、箭头方向、端点、遗漏和擅自补充，尤其关注 pic2 的物体分组与未标注部分。

官方调用依据：[GPT‑6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) · [Responses 图片输入](https://developers.openai.com/api/docs/guides/images-vision)。
