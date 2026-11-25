# 迭代说明：OCR 工具 → 忠实誊录 Agent（2026-11-25）

## 改了什么

在既有「逐列旋转 OCR + 视觉版面分区」骨架上，增加忠实誊录 Agent 层，吸收客户五条宪法与 6 阶段工作流精神。

| 阶段 | 内容 | Commit |
|------|------|--------|
| Phase 0 | DeepSeek-flash 字符级 spike（`/tmp`，未入库） | — |
| Phase 1 | 聚合/纠错 prompt 注入忠实誊录宪法；`□`→`〔待辨〕` | `219518a` |
| Phase 2 | 可选多引擎交叉、`glyph_arbiter` 候选约束仲裁、`P01-B01-C01-L01` 覆盖清单 | `267522a` |
| Phase 3 | `TranscriptionAgent` 最多 3 轮自检回炉；校勘报告 JSON/MD；export 接口 | 见 git log |

### Phase 0 spike 结论

- 合成清晰繁体字：exact **100%**
- 报纸真实 crop **开放辨认**：与 OCR 一致率偏低，但〔待辨〕行为健康
- **候选约束仲裁**：抽样 5/5 正确（含原先开放辨认失败的「要目」「丁名楠」）
- **决策**：Phase 2 采用「多引擎交叉为主 + 候选约束 VLM 为辅」；不做整页/开放式 VLM 转写

### 新增模块

- `backend/glyph_arbiter.py` — 候选约束字形仲裁（低置信→〔待辨〕）
- `backend/coverage.py` — 区域索引与覆盖核对
- `backend/transcription_agent.py` — 组装→自检→回炉循环
- `backend/collation_report.py` — 校勘与完整性报告

## 怎么用

1. 配置 `backend/.env` 的 `DEEPSEEK_API_KEY`（勿提交）。视觉模型默认 `deepseek-flash`。
2. 启动后端，上传 PDF，走默认 `columnwise` 流程（版面→逐列 OCR→Agent 聚合）。
3. 产物：
   - `corrected.json` / `corrected.txt` — 繁体誊录稿
   - `collation_report.json` / `collation_report.md` — 校勘报告
   - 下载：`GET /api/tasks/<id>/export/collation` 与 `.../collation-md`
4. 可选：安装 `requirements-paddle.txt` 后设 `OCR_MULTI_ENGINE=true`（默认尝试加载第二引擎；未装 Paddle 时静默单引擎）。
5. `correction_mode=conservative` 仍可启用繁→繁误识表（租酸→組織等）。

## 遗留问题

1. PaddleOCR 当前环境未安装，多引擎交叉在生产需另装依赖后才生效。
2. 字形仲裁目前对**整块 crop** 做候选选择，尚无真正的单字级检测框切分；冲突密集时精度有限。
3. Agent 自检是启发式（虚增/萎缩比、今本→今天探针、覆盖清单），不能替代人工回原图。
4. 端到端仍受 RapidOCR 竖排繁体固有错字率制约；VLM 只兑冲突/低置信，不重做整页转写。
5. 客户反馈中的「无换行」依赖聚合 prompt 保留栏/段层次，需持续用真页肉眼回归。
6. 端到端（1945 現代週刊 p1）：已产出誊录稿+校勘报告、有换行层次；`幾十年來`/`開放` 未再被改成「十幾年來/放開」。若 OCR raw 已是「今天」而非「今本」，Agent 探针无法回改——需字符级 crop 仲裁增强后才能兑。目录人名（丁名楠等）仍可能错。
