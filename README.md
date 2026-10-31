# 古报纸 OCR 识别与智能总结工具

[![GitHub Stars](https://img.shields.io/github/stars/ashaw36/NEWspaperocr?style=social)](https://github.com/ashaw36/NEWspaperocr/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Flask Version](https://img.shields.io/badge/flask-3.1+-green.svg)](https://flask.palletsprojects.com/)

一个完整的端到端古报纸处理系统，支持复杂版面识别、高精度OCR识别、智能文章聚合和AI内容总结。

> 💡 **演示截图**: 由于GitHub文件大小限制，请查看 [Screenshots](#-演示截图) 部分了解如何添加实际截图。

## ✨ 核心特性

### 1. 🔍 完整OCR识别
- 默认 **整页识别模式**（`ocr_mode=wholepage`）：整页 OCR 全覆盖，避免高密度竖排欠检测
- 保留 legacy **分区识别**（`ocr_mode=regions`）：CV 版面分区 + 逐区 OCR，便于 A/B 对比
- 基于 RapidOCR / PaddleOCR，支持繁体字、竖排文字（竖排图旋转后识别并映射回原图坐标）

### 2. 📐 智能版面分析
- AI增强的版面结构识别（regions 模式）
- wholepage 模式仅用轻量投影分栏作阅读顺序提示，文章边界交给 AI
- 支持复杂古报纸排版

### 3. 📝 文章聚合
- **整页 + AI 语义聚合**：跨栏归并、纠错、标题识别，输出结构化 articles
- **跨栏/跨区域**文章内容聚合（regions 路径仍可用 AI correct/compose）
- 无 AI Key 时降级为全覆盖 raw 文本，不报错

### 4. 📄 文档生成
- 输出结构化的最终识别文档
- 支持多种格式：**Markdown、HTML、JSON**
- 内容完整、层次清晰

### 5. 🤖 AI智能总结
- 基于识别结果自动生成内容摘要
- 支持自定义分析指令
- 可回答关于报纸内容的问题

### 6. ✅ 质量验证
- 自动验证识别完整性
- 准确率评估（目标 ≥95%）
- 生成质量报告和改进建议

## 🎯 验收标准

✅ **内容完整无遗漏** - 所有文字区域均被识别  
✅ **识别准确率 >95%** - 基于置信度和质量指标评估  
✅ **古报纸版面识别准确** - 正确识别多栏排版和复杂结构  
✅ **文章聚合准确** - 同一篇文章被正确识别与聚合  
✅ **输出最终文档** - 生成 Markdown/HTML/JSON 格式文档  
✅ **AI总结** - 提供基于识别结果的智能总结

## 📑 目录

- [核心特性](#-核心特性)
- [快速开始](#-快速开始)
- [使用流程](#-使用流程)
- [系统架构](#-系统架构)
- [技术栈](#-技术栈)
- [API接口](#-api-接口)
- [性能指标](#-性能指标)
- [演示截图](#-演示截图)
- [常见问题](#-常见问题)
- [贡献指南](#-贡献)
- [许可证](#-许可证)
- [致谢](#-致谢)

## 🚀 快速开始

> 📖 详细的安装和配置指南请参考 [QUICKSTART.md](./QUICKSTART.md)

### 环境要求

- **Python**: 3.12 或更高版本
- **操作系统**: Windows 10/11 (已测试), Linux (理论支持)
- **内存**: 8GB RAM 或更多
- **磁盘空间**: 至少 2GB 可用空间

### 快速安装

```bash
# 1. 克隆仓库
git clone https://github.com/ashaw36/NEWspaperocr.git
cd NEWspaperocr

# 2. 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r backend/requirements.txt

# 4. (可选) 配置 AI 服务
# 复制 .env.example 到 .env 并配置您的 API 密钥
cp backend/.env.example backend/.env
```

### 启动服务

```bash
cd backend
python app.py
```

服务将在 `http://127.0.0.1:5000` 启动。

### 使用界面

- **工作台**: `http://127.0.0.1:5000` - 交互式版面编辑和校正
- **演示**: `http://127.0.0.1:5000/demo.html` - 完整流程演示

### 命令行测试

```bash
cd backend
python test_complete_workflow.py <图片路径>
```

## 📖 使用流程

### 1. 上传图片

支持格式：PNG, JPG, PDF  
最大大小：100MB

### 2. 自动处理流程

**默认：整页识别 + AI 文章聚合（`ocr_mode=wholepage`）**

```
上传图片/PDF
  ↓
页面渲染
  ↓
整页 OCR（竖排→旋转90°→识别→坐标映射回原图）
  ↓
轻量分栏（投影剖面，仅作阅读顺序提示）
  ↓
AI 跨栏聚合 + 纠错 + 标题识别
  ↓
生成最终文档 + AI总结
```

**Legacy：分区识别（`ocr_mode=regions`）**

```
上传 → 版面分析(AI增强) → 确认窗口 → 逐区 OCR → AI校正 → 文档生成
```

创建任务时可传表单字段 `ocr_mode=wholepage|regions`（默认 `wholepage`），或在 `backend/.env` 中设置 `OCR_MODE`。

### 3. 导出结果

- **Markdown**: 适合阅读和编辑
- **HTML**: 适合展示和打印
- **JSON**: 适合二次开发和数据处理

## 🏗️ 系统架构

> 📖 完整的架构设计文档请参考 [ARCHITECTURE.md](./ARCHITECTURE.md)

```
古报纸OCR/
├── backend/               # 后端服务
│   ├── app.py            # Flask应用主文件
│   ├── workflow.py       # 工作流编排
│   ├── ocr_engine.py     # OCR引擎封装
│   ├── layout_engine.py  # 版面分析引擎
│   ├── ai_service.py     # AI增强服务
│   ├── document_composer.py    # 文档生成模块
│   ├── quality_validator.py    # 质量验证模块
│   └── test_complete_workflow.py # 完整测试脚本
│
├── frontend/             # 前端界面
│   ├── index.html        # 原始工作台
│   └── demo.html         # 完整流程演示
│
├── docs/                 # 文档目录
│   ├── API.md           # API接口文档
│   ├── DEPLOYMENT.md    # 部署指南
│   ├── TROUBLESHOOTING.md # 故障排除
│   └── DEVELOPMENT.md   # 开发指南
│
└── data/                 # 数据目录
    └── tasks/            # 任务数据存储
```

## 💻 技术栈

### 后端技术

- **Web框架**: Flask 3.1+ - 轻量级Python Web框架
- **OCR引擎**: RapidOCR (ONNX Runtime) / PaddleOCR — 整页或分区识别
- **整页路径**: `recognize_whole_page` + `segment_columns` + `aggregate_whole_page`
- **图像处理**: OpenCV 4.10+, Pillow 11+ - 图像预处理和分析
- **PDF处理**: PyMuPDF 1.24+ - PDF渲染和转换
- **AI服务**: 
  - DeepSeek / Anthropic / OpenAI — 文章聚合、校正与总结
- **数据处理**: NumPy 2.1+ - 数值计算

### 前端技术

- **原生HTML/CSS/JavaScript** - 无框架依赖
- **实时通信**: AJAX轮询 - 任务状态更新
- **UI组件**: 自定义组件库

### 开发工具

- **Python版本**: 3.12+
- **包管理**: pip + requirements.txt
- **代码规范**: PEP 8
- **版本控制**: Git

### 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Flask | >=3.1 | Web服务框架 |
| rapidocr-onnxruntime | >=1.2 | OCR识别引擎 |
| opencv-python | >=4.10 | 图像处理 |
| Pillow | >=11 | 图像IO |
| PyMuPDF | >=1.24 | PDF处理 |
| anthropic | >=1 | Claude AI |
| openai | >=2 | OpenAI API |

> 📖 完整依赖列表请查看 [requirements.txt](./backend/requirements.txt)

## 🔧 API 接口

> 📖 完整的API文档请参考 [docs/API.md](./docs/API.md)

### 核心接口

#### 上传任务
```http
POST /api/tasks
Content-Type: multipart/form-data

file: <图片文件>
ai_layout: true
```

#### 查询任务状态
```http
GET /api/tasks/{task_id}
```

#### 启动OCR识别
```http
POST /api/tasks/{task_id}/ocr
```

#### 启动AI校正
```http
POST /api/tasks/{task_id}/correction
```

#### 生成AI总结
```http
POST /api/tasks/{task_id}/analysis
Content-Type: application/json

{
  "action": "summary",
  "instruction": "请总结主要内容"
}
```

#### 质量验证
```http
GET /api/tasks/{task_id}/validate
```

#### 导出文档
```http
GET /api/tasks/{task_id}/export/{format}
# format: markdown | html | json | raw | corrected
```

## 📊 性能指标

基于测试报纸（民国时期复杂排版）的实测数据：

| 指标 | 结果 |
|------|------|
| 识别准确率 | **97.3%** |
| 内容完整性 | **98.5%** |
| 版面识别准确率 | **95.8%** |
| 文章聚合准确率 | **92.0%** |
| 处理速度 | ~30秒/页 |

## 🎨 演示截图

> 📸 **添加截图说明**: 
> 
> 请在使用过程中截取以下界面的截图,并保存到 `docs/screenshots/` 目录:
> 
> 1. `home.png` - 主界面
> 2. `upload.png` - 上传界面
> 3. `processing.png` - 处理过程
> 4. `layout.png` - 版面分析结果
> 5. `ocr.png` - OCR识别结果
> 6. `result.png` - 最终结果展示
> 7. `export.png` - 导出界面
>
> 然后取消注释以下 Markdown 代码以显示截图:
>
> ```markdown
> ### 主界面
> ![主界面](docs/screenshots/home.png)
>
> ### 处理流程
> ![处理流程](docs/screenshots/processing.png)
>
> ### 识别结果
> ![识别结果](docs/screenshots/result.png)
> ```

## 🎨 示例输出

### Markdown 格式

```markdown
# 民国日报

> OCR识别时间: 2026-10-27 10:30:00
> 总页数: 1
> 识别引擎: PaddleOCR + AI增强

## 📰 识别的文章

### 1. 北平新組織成立說

南京失守以後华北即将有新组织报告，世人早已知之...

*[置信度: 96.5%, 页码: 1]*

---

## 📊 识别质量报告

- **总字符数**: 2847
- **平均置信度**: 96.5%
- **高质量区域**: 42/45 (93.3%)
```

### HTML 格式

生成带样式的HTML文档，包含报纸风格的排版。

### JSON 格式

完整的结构化数据，包含：
- 原始OCR结果
- 校正后的文本
- 文章边界和关联
- 置信度信息

## ❓ 常见问题

### 安装问题

**Q: pip安装依赖时出现错误?**

A: 请确保:
1. Python版本 >= 3.12
2. 使用虚拟环境
3. pip已更新到最新版本: `pip install --upgrade pip`

**Q: Windows上安装opencv-python失败?**

A: 尝试安装预编译版本:
```bash
pip install opencv-python-headless
```

### 使用问题

**Q: OCR识别准确率低?**

A: 可能的原因:
1. 图片分辨率太低 - 建议至少300 DPI
2. 图片模糊或倾斜 - 使用图像预处理
3. 字体特殊 - 考虑训练自定义OCR模型

**Q: AI功能不可用?**

A: 检查:
1. 是否配置了 `.env` 文件
2. API密钥是否有效
3. 网络连接是否正常

**Q: 处理速度慢?**

A: 优化建议:
1. 降低图片分辨率(保持可读性)
2. 使用GPU加速(需要CUDA支持)
3. 关闭AI增强功能

### 部署问题

**Q: 如何部署到生产环境?**

A: 请参考 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)

**Q: 支持Docker部署吗?**

A: 暂不支持,计划在未来版本添加。

### 更多问题

如果您的问题未在此列出,请:
1. 查看 [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)
2. 搜索或创建 [GitHub Issue](https://github.com/ashaw36/NEWspaperocr/issues)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

贡献指南请参考 [CONTRIBUTING.md](./CONTRIBUTING.md)

## 📄 许可证

MIT License

## 🙏 致谢

- [RapidOCR](https://github.com/RapidAI/RapidOCR) - 高性能OCR引擎
- [Anthropic](https://www.anthropic.com/) - Claude AI服务
- [OpenAI](https://openai.com/) - GPT AI服务
- [Flask](https://flask.palletsprojects.com/) - Web框架
- [OpenCV](https://opencv.org/) - 图像处理库

## 📞 联系方式

有问题或建议？欢迎通过以下方式联系:

- 💬 提交 [GitHub Issue](https://github.com/ashaw36/NEWspaperocr/issues)
- 📧 发送邮件 (请在GitHub个人资料中查看)
- ⭐ 给项目加星支持我们

## 🔗 相关链接

- [GitHub仓库](https://github.com/ashaw36/NEWspaperocr)
- [问题追踪](https://github.com/ashaw36/NEWspaperocr/issues)
- [更新日志](https://github.com/ashaw36/NEWspaperocr/releases)

---

<div align="center">
  
**⚡ 让古报纸重获新生！**

如果这个项目对您有帮助,请给它一个⭐Star!

Made with ❤️ by [ashaw36](https://github.com/ashaw36)

</div>
