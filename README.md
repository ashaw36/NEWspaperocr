# 古报纸识读工作台

面向历史报纸研究的可审核 OCR 工作流。系统不会在上传后直接把整页送入 OCR，而是先生成带语义标签和阅读顺序的 OCR 窗口，允许研究者确认后再识别。

## 工作流

1. **版面规划**：逐页渲染 PDF，通过图像结构提出窗口；AI 可用时复核窗口类型、文章分组和阅读顺序。
2. **人工确认**：在页面上新增、移动、缩放、删除窗口，编辑类型、方向、文章分组和顺序。
3. **OCR**：默认只识别当前页，也可明确选择全部页面；每完成一页就保存结果。原始文本可以人工修订。
4. **AI 校正**：选择当前页或全部已识别页，按窗口顺序和文章分组重组文本，修正高概率 OCR 错字，同时保存修改理由和不确定项。AI 草稿可继续人工定稿。
5. **研究分析**：优先使用校正稿；未校正页面自动回退到原始 OCR。可以生成总结、实体、主题，也可以基于全文提问。

AI 没有配置时，版面编辑和 OCR 仍可使用；系统不会生成伪造的 Mock 文本。

## 启动

```powershell
cd backend
py -m pip install -r requirements.txt
py app.py
```

另开一个终端：

```powershell
cd frontend
py -m http.server 8080
```

访问 `http://127.0.0.1:8080`。Windows 也可以双击 `启动系统.bat`。

首页的“最近任务”可以恢复刷新前或服务中断前的工作。长文档建议先逐页确认和 OCR，确认效果后再处理全部页面。

## 配置 AI

将 `backend/.env.example` 复制为 `backend/.env`，然后填写 `DEEPSEEK_API_KEY`。默认使用 `deepseek-chat`，用于逐页语义校正、全文总结和问答；DeepSeek 当前文本模型不负责图片版面复核，版面分析会使用本地计算机视觉。需要换模型时修改 `DEEPSEEK_MODEL`，需要换服务商时设置 `AI_PROVIDER`。

DeepSeek 配置示例：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=填入你的 DeepSeek API Key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

不要把真实 `.env` 提交到 Git，也不要把 API Key 发到聊天中。修改后重启 `backend/app.py`，打开 `/api/health` 时应看到 `ai.available: true` 和 `ai.backend: deepseek`。

## 命令行

命令行使用与 Web 相同的任务、版面和 OCR 实现：

```powershell
cd backend
py process_newspaper.py "..\1945-01-01(1).pdf" -o results_cli -p 3 --dpi 180
```

需要 AI 时添加 `--ai-layout` 和/或 `--ai-correct`。命令行没有人工确认步骤，因此会直接采用自动窗口；需要严谨校对时应使用 Web 工作台。

## 任务数据

每个任务保存在 `backend/results_v2/<task-id>/`：

```text
task.json          任务状态、页面和确认后的版面
pages/             逐页原始渲染图
crops/             实际送入 OCR 的窗口裁剪图
ocr.json           原始 OCR、坐标、置信度与窗口元数据
raw.txt            按确认顺序组合的原始文本
corrected.json     AI 校正、文章结构、修改记录和警告
corrected.txt      AI 组合后的全文
```

窗口包含 `bbox`、`label`、`article_id`、`direction`、`order`、`source`、`confidence` 和 `notes`。坐标统一为相对于页面宽高的 0 到 1 浮点数。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/health` | OCR 与 AI 能力状态 |
| `POST` | `/api/tasks` | 上传并异步分析版面 |
| `GET` | `/api/tasks` | 最近任务列表 |
| `GET` | `/api/tasks/<id>` | 任务状态、进度和版面 |
| `PUT` | `/api/tasks/<id>/layout` | 保存用户编辑后的窗口 |
| `POST` | `/api/tasks/<id>/ocr` | 确认版面并按选定页面异步 OCR |
| `GET` | `/api/tasks/<id>/ocr` | 原始 OCR 结果 |
| `PUT` | `/api/tasks/<id>/ocr` | 保存人工修订的原始文本 |
| `POST` | `/api/tasks/<id>/correction` | 启动 AI 语义校正 |
| `GET` | `/api/tasks/<id>/correction` | 获取 AI 校正结果 |
| `PUT` | `/api/tasks/<id>/correction` | 保存人工最终校正稿 |
| `POST` | `/api/tasks/<id>/analysis` | 总结或基于全文问答 |
| `GET` | `/api/tasks/<id>/export/<kind>` | 导出 `raw`、`corrected` 或 `json` |

## 核心模块

- `task_store.py`：任务清单、状态和原子写入。
- `pdf_processor.py`：使用 PyMuPDF 按页渲染，避免整份 PDF 同时常驻内存。
- `layout_engine.py`：正文栏、横排行和框线网格的候选窗口生成。
- `ocr_engine.py`：RapidOCR/PaddleOCR 适配、显式错误和窗口内排序。
- `ai_service.py`：视觉版面复核、语义纠错、总结和问答。
- `workflow.py`：各阶段状态机与结果组装。
- `app.py`：异步任务 API、页面/裁剪图和导出接口。

## 当前边界

- 自动窗口是可审核建议，不应代替研究者对复杂版面的确认。
- AI 修订与原始 OCR 分开保存；重要引文应回看裁剪图和原版。
- 当前后台任务运行在单机线程池中。大量并发时应替换为正式任务队列和共享存储。
- 准确率必须通过人工标注的 CER/WER、区域召回率和阅读顺序指标评估，不能用模型置信度代替。
