# 后端服务 Backend Service

古报纸OCR系统的后端服务,基于Flask构建。

## 📋 目录

- [架构概述](#架构概述)
- [模块说明](#模块说明)
- [API接口](#api接口)
- [开发指南](#开发指南)
- [测试](#测试)

## 架构概述

后端采用模块化设计,各模块职责清晰:

```
backend/
├── app.py                 # Flask应用入口,路由定义
├── workflow.py            # 工作流编排,协调各模块
├── ocr_engine.py          # OCR识别引擎封装（含 recognize_whole_page）
├── column_segmenter.py    # 整页模式轻量分栏（投影剖面）
├── layout_engine.py       # 版面分析引擎（regions 路径）
├── ai_service.py          # AI服务集成(聚合/校正/总结)
├── document_composer.py   # 文档生成器(MD/HTML/JSON)
├── quality_validator.py   # 质量验证模块
├── task_store.py          # 任务数据持久化
├── image_io.py            # 图像IO工具
├── pdf_processor.py       # PDF处理工具
└── tests/                 # 单元测试
```

## 模块说明

### app.py - Flask应用

**职责**: Web服务入口,HTTP路由处理

**核心路由**:
- `POST /api/tasks` - 创建OCR任务
- `GET /api/tasks/{id}` - 查询任务状态
- `POST /api/tasks/{id}/ocr` - 启动OCR识别
- `POST /api/tasks/{id}/correction` - AI校正
- `POST /api/tasks/{id}/analysis` - AI分析总结
- `GET /api/tasks/{id}/validate` - 质量验证
- `GET /api/tasks/{id}/export/{format}` - 导出文档

### workflow.py - 工作流编排

**职责**: 协调OCR识别的完整流程

**核心流程**:
1. 接收图片上传（`options.ocr_mode`: `columnwise` 默认 / `wholepage` / `regions` legacy）
2. 版面分析(可选AI增强；columnwise/regions 需要视觉 region 边界)
3. OCR：`run_columnwise_ocr`（逐列旋转）/ `run_wholepage_ocr`（整页）/ `run_ocr`（legacy 分区）
4. AI 聚合/校正
5. 文档生成（columnwise/wholepage 走 `compose_from_ai_articles`）
6. 质量验证

### ocr_engine.py - OCR引擎

**职责**: 封装OCR识别功能

**使用引擎**: RapidOCR (基于ONNX Runtime) / PaddleOCR

**核心功能**:
- 文字区域检测与分区识别（`recognize`）
- 整页识别（`recognize_whole_page`：竖排旋转、bbox 映射回原图）
- 置信度评估
- 支持繁体字和竖排文字

### layout_engine.py - 版面分析

**职责**: 分析报纸版面结构

**核心功能**:
- 区域检测与分割
- 区域类型分类(标题/正文/图片/广告)
- AI增强分析
- 文章边界识别

### ai_service.py - AI服务

**职责**: 集成AI能力增强识别质量

**支持的AI服务**:
- Anthropic Claude API
- OpenAI GPT API

**核心功能**:
- OCR错误校正
- 文章智能聚合
- 内容总结生成
- 问答交互

### document_composer.py - 文档生成

**职责**: 将识别结果转换为结构化文档

**支持格式**:
- Markdown - 适合阅读和编辑
- HTML - 适合展示和打印
- JSON - 适合二次开发

**内容包含**:
- 识别的文章内容
- 元数据信息
- 质量统计
- 格式化排版

### quality_validator.py - 质量验证

**职责**: 验证识别结果质量

**验证维度**:
- 完整性 - 是否有遗漏
- 准确率 - 识别置信度
- 版面质量 - 结构识别准确性
- 文章聚合 - 聚合正确性

**验收标准**:
- 整体评分 ≥ 95分
- 各项指标达标

### task_store.py - 任务存储

**职责**: 任务数据的持久化管理

**存储结构**:
```
data/tasks/{task_id}/
├── upload/           # 原始上传文件
├── pages.json        # 版面分析结果
├── ocr_result.json   # OCR识别结果
├── correction.json   # AI校正结果
├── raw.txt           # 原始识别文本
├── corrected.txt     # 校正后文本
├── final.md          # Markdown文档
├── final.html        # HTML文档
└── validation.json   # 质量验证报告
```

## API接口

详细的API文档请参考: [docs/API.md](../docs/API.md)

### 快速示例

**创建任务**:
```bash
curl -X POST http://localhost:5000/api/tasks \
  -F "file=@newspaper.jpg" \
  -F "ai_layout=true"
```

**查询状态**:
```bash
curl http://localhost:5000/api/tasks/{task_id}
```

**导出Markdown**:
```bash
curl http://localhost:5000/api/tasks/{task_id}/export/markdown
```

## 开发指南

### 环境配置

```bash
# 创建虚拟环境
python -m venv ../.venv
source ../.venv/bin/activate  # Linux/Mac
..\.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置文件

创建 `.env` 文件:

```env
# 开发模式
FLASK_ENV=development
FLASK_DEBUG=1

# AI服务(可选)
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key

# 数据目录
DATA_DIR=./data
```

### 启动开发服务器

```bash
python app.py
```

服务将在 `http://127.0.0.1:5000` 启动。

### 代码规范

- 遵循 PEP 8 代码规范
- 使用类型注解
- 编写文档字符串
- 保持函数简洁

### 添加新功能

1. 在相应模块中实现功能
2. 在 `app.py` 中添加路由
3. 在 `workflow.py` 中集成到流程
4. 编写单元测试
5. 更新文档

## 测试

### 运行单元测试

```bash
# 安装测试依赖
pip install pytest pytest-cov

# 运行测试
pytest tests/ -v

# 生成覆盖率报告
pytest tests/ --cov=. --cov-report=html
```

### 测试特定模块

```bash
# 测试OCR引擎
pytest tests/test_ocr.py

# 测试工作流
pytest tests/test_workflow.py

# 测试API
pytest tests/test_api.py
```

### 集成测试

```bash
# 完整工作流测试
python test_complete_workflow.py sample_newspaper.jpg

# 模块测试
python test_modules.py
```

## 性能优化

### OCR识别优化

- 图片预处理(去噪,二值化)
- 合理的分辨率(300-600 DPI)
- GPU加速(如果可用)

### 并发处理

- 使用Gunicorn多worker
- 异步任务队列(Celery)
- 缓存中间结果

### 内存管理

- 及时清理临时文件
- 使用生成器处理大数据
- 限制并发任务数

## 依赖说明

### 核心依赖

- **Flask** (>=3.1) - Web框架
- **rapidocr-onnxruntime** (>=1.2) - OCR引擎
- **opencv-python** (>=4.10) - 图像处理
- **Pillow** (>=11) - 图像IO
- **PyMuPDF** (>=1.24) - PDF处理

### AI依赖(可选)

- **anthropic** (>=1) - Claude AI
- **openai** (>=2) - OpenAI API

完整依赖列表见 `requirements.txt`

## 故障排查

常见问题请参考: [docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md)

## 贡献

欢迎贡献代码!请参考: [CONTRIBUTING.md](../CONTRIBUTING.md)

---

**维护者**: ashaw36  
**最后更新**: 2026-10-27
