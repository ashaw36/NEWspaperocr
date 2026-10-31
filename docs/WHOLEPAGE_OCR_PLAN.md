# 整页识别 + AI 文章聚合 方案（v3 模式）

> 目标：用「整页 OCR + AI 语义聚合」替换现有「CV 版面分区 + 逐区 OCR」，解决高密度竖排古报纸的分区欠检测问题。
> 原则：新增 `ocr_mode="wholepage"` 路径，**保留** legacy `regions` 路径（feature flag 可切换，便于 A/B 对比）。

---

## 1. 现状问题（实测）

- 测试页 `返乡运动会之垦殖班.pdf`（民国晶报，竖排繁体、高密度）：
  - `layout_engine.propose()`（CV fallback）只检出 **7 个区域**，且全在页面左侧（x∈[0.09,0.29]），主体文章（右侧竖排）全部漏检。
  - 逐区 OCR 结果仅 409 字节，只覆盖「售書部」书价栏。
- 根因：`_column_boxes`/`_group_columns`/`_split_oversized_vertical_regions` 的形态学闭运算 + 阈值过滤，在密集竖排文字上把相邻栏合并成超宽区域后被 `w > width*0.45` 丢弃。
- AI 侧 `correct_page`/`compose_page` 已具备「按 article_id 聚合 + 语义校正」能力，但输入被烂分区污染。

---

## 2. 方案总览

```
整页渲染(高DPI)
   ↓
整页 OCR（竖排→旋转90°→OCR→坐标映射回原图）   ← 全覆盖
   ↓
轻量分栏（投影剖面 → 列带）                     ← 仅作阅读顺序提示
   ↓
AI 聚合（跨栏归并 + 阅读顺序 + 纠错 + 标题识别） ← 语义交给 AI
   ↓
文档生成（markdown/html/json）
```

新增 `task.options.ocr_mode ∈ {"regions"(legacy), "wholepage"(default)}`。

---

## 3. 分步实现（每个文件改什么）

### 3.1 `ocr_engine.py` — 整页 OCR

新增方法 `recognize_whole_page(image, direction="vertical-rtl") -> Dict`：

1. 若 `direction == "vertical-rtl"`：对整页 `cv2.rotate(img, ROTATE_90_CLOCKWISE)` 后再 OCR（让竖排列变成横向行）。
2. 复用现有 `_rapid_blocks` 拿到 text/confidence/bbox。
3. **把 bbox 从旋转空间映射回原图坐标**：
   - 旋转前原图尺寸 `(H, W)`，旋转后 `(W, H)`。
   - 旋转空间点 `(xr, yr)` → 原图 `(x, y) = (yr, H - xr)`。
   - 对每个 block 的 4 点多边形逐点映射，保证 bbox 落回原图空间。
4. 返回 `{"blocks":[{text,confidence,bbox(原图坐标)}], "full_text", "total_blocks", "confidence", "quality"}`。
5. 若 `direction == "horizontal-ltr"`：直接 OCR，不旋转，bbox 即为原图坐标。

> 说明：full_text 的阅读顺序仍可能是乱的（RapidOCR 按 y 排序），顺序交给 AI（3.3）处理，这里只保证「内容全覆盖 + 坐标正确」。

### 3.2 轻量分栏（可放 `layout_engine.py` 新增方法，或新文件 `column_segmenter.py`）

新增 `segment_columns(image, direction) -> List[Dict]`，**不要复用/改动现有 `propose()`**：

1. 竖排：旋转 90°CW 后，对灰度图做水平投影 `projection = ink.sum(axis=1)`。
2. 找列带：投影值低于阈值（如 `max(1, percentile*0.15)`）的连续行视为「列间空隙」，据此切分出行带（每带 = 一个原始竖排列）。
3. 为每个 OCR block 按其旋转空间 y 中心落入哪个带，赋 `column_index`。
4. 返回列带列表，每项含 `{column_index, y_range(旋转空间), x_center(原图列位置)}`。
5. 列阅读顺序：原图右→左（x 降序）；带内：原图上→下（旋转后 x 降序）。把这些约定写进注释，AI 提示词也引用。

> 这一层只是「提示」，允许不完美；真正的文章边界与顺序由 AI 判定。

### 3.3 `ai_service.py` — 整页聚合方法

新增 `aggregate_whole_page(page_number, blocks, columns, page_image=None) -> Dict`：

- 输入：blocks（含 text/confidence/bbox/column_index）+ columns（列带元信息）+ 阅读方向。
- Prompt 要点：
  1. 输入是「竖排繁体民国报纸整页 OCR 文本块（含坐标与列索引）」，阅读方向 vertical-rtl（列右→左、列内上→下）。
  2. 任务：跨栏/跨区域聚合为文章；确定标题/副标题/正文/报头/广告；纠正 OCR 错字（如「齊爕元」→「齊燮元」，保留繁体、历史措辞、人名地名，不臆造）。
  3. 输出 JSON：`{"articles":[{"id","title","subtitle","body","direction"}], "corrected_text","corrections":[{"block_id","original","corrected","reason","confidence"}], "warnings":[]}`。
- 实现：优先 `self._text_json(prompt, max_tokens=…)`（deepseek-chat 文本模型即可）；若 `supports_vision` 且有 `page_image`，可选将整页图作为视觉交叉校验（沿用 `_vision_json`，失败则回退文本，勿抛错中断）。
- 大页保护：blocks 全量文本若超 ~60000 字符，按列分块调用后合并。

### 3.4 `workflow.py` — 接入新路径

新增 `run_wholepage_ocr(task_id, page_numbers=None)`：

1. 渲染页面（复用现有 `PDFProcessor`/`render_document` 逻辑，已有 `page_XXX.png` 直接用）。
2. 每页：`self.ocr.recognize_whole_page(image, direction)` → `segment_columns` → 给 blocks 打 `column_index`。
3. 若 `self.ai.available`：调 `aggregate_whole_page` 得到 articles/corrected_text，写入 `corrected.json`（结构对齐现有 `_save_corrected_result`，pages[].articles 存聚合结果）；否则仅存整页 raw 文本（全覆盖、无聚合）。
4. 写 `ocr.json`（新结构 `pages[].blocks` + `pages[].raw_text` + `pages[].columns`），并写 `raw.txt`。
5. 状态机：复用 `ocr_ready` / stage `ocr`；`task.options.mode="wholepage"`；progress 消息中文。

分支改造：在 `queue_ocr`/`run_ocr` 入口判断 `task["options"].get("ocr_mode")=="wholepage"` → 走 `run_wholepage_ocr`，否则走原 `run_ocr`（**原逻辑一字不动**）。

### 3.5 `document_composer.py` — 从 AI 文章直接生成

新增 `compose_from_ai_articles(articles, task_data) -> str`（markdown；html 同理）：

- 直接按 AI 给出的 `title/subtitle/body` 顺序渲染文章列表，不再依赖 `_extract_articles` 的 article_id 拼装。
- `generate_final_document` 中：若 `options.ocr_mode=="wholepage"` 且有 articles，走新方法；否则走原路径。

### 3.6 `app.py` + `.env.example` — 开关与配置

- `create_task`：读表单 `ocr_mode`（默认 `"wholepage"`），存入 `options`。
- `.env.example` 增 `OCR_MODE=wholepage`（默认值说明）。
- 保留 `/api/tasks/<id>/ocr` 等端点不变，内部按 `ocr_mode` 分流。

---

## 4. 关键约束 / 注意事项

1. **不破坏 legacy**：`regions` 路径所有现有函数保持原样，新代码用新函数名。
2. **AI 不可用降级**：无 key 时整页 OCR 仍产出「全覆盖 raw 文本」，只是不聚合；不要因缺 AI 报错。
3. **旋转坐标映射**务必单测（拿一个已知竖排 block 验证映射回原图位置正确）。
4. **繁体保留**：AI 提示词明确「保留繁体、不现代化、不臆造、□ 表不可读」。
5. **大文件分块**：多页/大页注意 token 上限，分块聚合。
6. 完成后更新 `backend/README.md` 与根 `README.md` 的「使用流程/技术栈」说明新模式。

## 5. 验证标准

- 用 `返乡运动会之垦殖班.pdf` 对比：regions 模式 vs wholepage 模式。
- 验收：wholepage 模式 raw 文本字符数显著大于 regions 模式（覆盖主体文章）；AI 聚合后能输出 ≥6 篇结构正确的文章（标题+正文+顺序正确）。
