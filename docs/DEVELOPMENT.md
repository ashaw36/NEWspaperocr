# 开发指南 Development Guide

本文档为开发者提供项目开发的详细指南。

## 📋 目录

- [开发环境搭建](#开发环境搭建)
- [项目结构](#项目结构)
- [核心模块说明](#核心模块说明)
- [开发工作流](#开发工作流)
- [测试指南](#测试指南)
- [代码风格](#代码风格)
- [调试技巧](#调试技巧)
- [扩展开发](#扩展开发)

## 开发环境搭建

### 1. 前置要求

- Python 3.12+
- Git
- 代码编辑器 (推荐 VS Code, PyCharm)
- Postman或类似工具 (用于API测试)

### 2. 克隆项目

```bash
git clone https://github.com/ashaw36/NEWspaperocr.git
cd NEWspaperocr
```

### 3. 配置开发环境

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install --upgrade pip
pip install -r backend/requirements.txt

# 安装开发依赖
pip install pytest pytest-cov black flake8 mypy
```

### 4. 配置环境变量

```bash
# 复制配置文件
cp backend/.env.example backend/.env

# 编辑配置
# Windows
notepad backend\.env
# Linux/Mac
nano backend/.env
```

`.env` 配置示例:

```env
# 开发模式
FLASK_ENV=development
FLASK_DEBUG=1

# AI服务 (可选)
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here

# 数据目录
DATA_DIR=./data
UPLOAD_DIR=./data/uploads

# 日志级别
LOG_LEVEL=DEBUG
```

### 5. IDE配置

#### VS Code

创建 `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.flake8Enabled": true,
  "python.linting.pylintEnabled": false,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  "[python]": {
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

创建 `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Flask App",
      "type": "python",
      "request": "launch",
      "module": "flask",
      "env": {
        "FLASK_APP": "backend/app.py",
        "FLASK_ENV": "development",
        "FLASK_DEBUG": "1"
      },
      "args": ["run", "--no-debugger", "--no-reload"],
      "jinja": true
    }
  ]
}
```

#### PyCharm

1. 设置Python解释器: File → Settings → Project → Python Interpreter
2. 选择虚拟环境: `.venv/bin/python`
3. 配置Flask运行配置

## 项目结构

```
NEWspaperocr/
├── backend/                    # 后端代码
│   ├── app.py                 # Flask应用入口
│   ├── workflow.py            # 工作流编排
│   ├── ocr_engine.py          # OCR引擎封装
│   ├── layout_engine.py       # 版面分析引擎
│   ├── ai_service.py          # AI服务集成
│   ├── document_composer.py   # 文档生成器
│   ├── quality_validator.py   # 质量验证器
│   ├── task_store.py          # 任务数据管理
│   ├── image_io.py            # 图像IO工具
│   ├── pdf_processor.py       # PDF处理
│   ├── config.py              # 配置管理(如需)
│   ├── utils.py               # 工具函数(如需)
│   └── tests/                 # 测试文件
│       ├── test_ocr.py
│       ├── test_workflow.py
│       └── test_api.py
│
├── frontend/                   # 前端代码
│   ├── index.html             # 主界面
│   ├── demo.html              # 演示界面
│   ├── css/                   # 样式文件
│   └── js/                    # JavaScript文件
│
├── data/                       # 数据目录
│   ├── tasks/                 # 任务数据
│   └── uploads/               # 上传文件
│
├── docs/                       # 文档
│   ├── API.md
│   ├── DEPLOYMENT.md
│   ├── TROUBLESHOOTING.md
│   └── DEVELOPMENT.md
│
├── tests/                      # 集成测试
│   └── integration/
│
├── .github/                    # GitHub配置
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│
├── README.md
├── CONTRIBUTING.md
├── LICENSE
└── requirements.txt
```

## 核心模块说明

### app.py - Flask应用

主要功能:
- Flask应用初始化
- 路由定义
- 请求处理
- 错误处理

核心路由:

```python
# 任务管理
POST   /api/tasks              # 创建任务
GET    /api/tasks/{task_id}    # 查询任务状态

# OCR处理
POST   /api/tasks/{task_id}/ocr          # 启动OCR
GET    /api/tasks/{task_id}/ocr/result   # 获取结果

# AI服务
POST   /api/tasks/{task_id}/correction   # AI校正
POST   /api/tasks/{task_id}/analysis     # AI分析

# 导出
GET    /api/tasks/{task_id}/export/{format}  # 导出文档

# 质量验证
GET    /api/tasks/{task_id}/validate     # 质量检查
```

### workflow.py - 工作流编排

负责协调各个模块的执行流程:

```python
class WorkflowManager:
    def process_task(self, task_id):
        """完整处理流程"""
        # 1. 版面分析
        pages = self.analyze_layout(task_id)
        
        # 2. OCR识别
        ocr_result = self.run_ocr(task_id, pages)
        
        # 3. AI校正
        corrected = self.ai_correction(task_id, ocr_result)
        
        # 4. 文档生成
        document = self.generate_document(task_id, corrected)
        
        # 5. 质量验证
        validation = self.validate_quality(task_id)
        
        return {
            'status': 'completed',
            'validation': validation
        }
```

### ocr_engine.py - OCR引擎

OCR识别的核心实现:

```python
class OCREngine:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.ocr = RapidOCR(
            text_score=0.5,
            use_angle_cls=True,
            use_text_det=True
        )
    
    def recognize(self, image_path):
        """执行OCR识别"""
        result, elapse = self.ocr(image_path)
        return self.parse_result(result)
    
    def parse_result(self, raw_result):
        """解析OCR结果"""
        text_blocks = []
        for item in raw_result:
            text_blocks.append({
                'text': item[1],
                'confidence': item[2],
                'bbox': item[0]
            })
        return text_blocks
```

### layout_engine.py - 版面分析

版面结构识别:

```python
class LayoutEngine:
    def analyze(self, image_path, use_ai=True):
        """分析版面结构"""
        # 1. 基础检测
        regions = self.detect_regions(image_path)
        
        # 2. 区域分类
        regions = self.classify_regions(regions)
        
        # 3. AI增强 (可选)
        if use_ai:
            regions = self.ai_enhance(regions)
        
        return regions
    
    def detect_regions(self, image_path):
        """检测文字区域"""
        # 使用OpenCV进行区域检测
        pass
    
    def ai_enhance(self, regions):
        """AI增强版面分析"""
        # 使用AI理解内容和优化区域
        pass
```

### ai_service.py - AI服务

AI功能集成:

```python
class AIService:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv('ANTHROPIC_API_KEY')
        )
    
    def correct_text(self, ocr_text, context=None):
        """AI文本校正"""
        prompt = self._build_correction_prompt(ocr_text, context)
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    
    def summarize(self, text, instruction):
        """生成内容总结"""
        pass
    
    def aggregate_articles(self, text_blocks):
        """文章聚合"""
        pass
```

### document_composer.py - 文档生成

生成多种格式的输出文档:

```python
class DocumentComposer:
    def generate_markdown(self, task_data):
        """生成Markdown文档"""
        pass
    
    def generate_html(self, task_data):
        """生成HTML文档"""
        pass
    
    def generate_json(self, task_data):
        """生成JSON数据"""
        pass
```

### quality_validator.py - 质量验证

验证识别质量:

```python
class QualityValidator:
    def validate(self, task_id):
        """执行质量验证"""
        results = {
            'completeness': self.check_completeness(task_id),
            'accuracy': self.check_accuracy(task_id),
            'layout_quality': self.check_layout(task_id),
            'article_aggregation': self.check_articles(task_id)
        }
        
        overall_score = self.calculate_score(results)
        results['overall_score'] = overall_score
        results['passed'] = overall_score >= 95.0
        
        return results
```

## 开发工作流

### 1. 功能开发流程

```bash
# 1. 创建功能分支
git checkout -b feature/your-feature-name

# 2. 开发功能
# 编写代码 → 编写测试 → 运行测试

# 3. 提交代码
git add <files>
git commit -m "feat: add new feature"

# 4. 推送分支
git push origin feature/your-feature-name

# 5. 创建Pull Request
```

### 2. Bug修复流程

```bash
# 1. 创建修复分支
git checkout -b bugfix/issue-123-description

# 2. 修复bug
# 定位问题 → 修复代码 → 添加测试

# 3. 验证修复
pytest tests/

# 4. 提交和推送
git commit -m "fix: resolve issue #123"
git push origin bugfix/issue-123-description
```

### 3. 代码审查

Pull Request应包含:
- 清晰的描述
- 相关测试
- 文档更新
- 代码符合规范

## 测试指南

### 单元测试

```python
# tests/test_ocr.py
import pytest
from backend.ocr_engine import OCREngine

def test_ocr_recognition():
    """测试OCR识别功能"""
    engine = OCREngine()
    result = engine.recognize('test_data/sample.jpg')
    
    assert len(result) > 0
    assert 'text' in result[0]
    assert 'confidence' in result[0]
    assert result[0]['confidence'] > 0.9

def test_ocr_with_invalid_image():
    """测试无效图片处理"""
    engine = OCREngine()
    with pytest.raises(Exception):
        engine.recognize('nonexistent.jpg')
```

### 集成测试

```python
# tests/test_workflow.py
import pytest
from backend.workflow import WorkflowManager

def test_complete_workflow():
    """测试完整工作流"""
    workflow = WorkflowManager()
    
    # 创建测试任务
    task_id = workflow.create_task('test_data/newspaper.jpg')
    
    # 执行处理
    result = workflow.process_task(task_id)
    
    assert result['status'] == 'completed'
    assert result['validation']['passed'] == True
    assert result['validation']['overall_score'] >= 95.0
```

### API测试

```python
# tests/test_api.py
import pytest
from backend.app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_create_task(client):
    """测试创建任务API"""
    with open('test_data/sample.jpg', 'rb') as f:
        response = client.post('/api/tasks', data={
            'file': f,
            'ai_layout': 'true'
        })
    
    assert response.status_code == 200
    data = response.get_json()
    assert 'task_id' in data

def test_get_task_status(client):
    """测试查询任务状态"""
    response = client.get('/api/tasks/test-task-id')
    assert response.status_code in [200, 404]
```

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_ocr.py

# 运行特定测试函数
pytest tests/test_ocr.py::test_ocr_recognition

# 生成覆盖率报告
pytest --cov=backend --cov-report=html

# 查看覆盖率报告
# 打开 htmlcov/index.html
```

## 代码风格

### Python代码规范

遵循 PEP 8:

```python
# ✅ 好的示例
def process_ocr_result(image_path: str, options: dict = None) -> dict:
    """
    处理OCR识别结果
    
    Args:
        image_path: 图片路径
        options: 可选配置
        
    Returns:
        dict: 处理结果
    """
    if options is None:
        options = {}
    
    result = {
        'text': '',
        'confidence': 0.0
    }
    
    return result


# ❌ 不好的示例
def processOCRResult(imagePath,options={}):  # 命名不规范,默认参数使用可变对象
    result={'text':'','confidence':0.0}  # 缺少空格
    return result
```

### 类型注解

使用类型提示:

```python
from typing import List, Dict, Optional

def analyze_layout(
    image_path: str,
    use_ai: bool = True
) -> List[Dict[str, any]]:
    """版面分析"""
    regions: List[Dict] = []
    return regions
```

### 文档字符串

使用Google风格或NumPy风格:

```python
def calculate_confidence(text_blocks: list) -> float:
    """
    计算平均置信度
    
    Args:
        text_blocks (list): 文本块列表
        
    Returns:
        float: 平均置信度 (0-100)
        
    Raises:
        ValueError: 如果text_blocks为空
        
    Example:
        >>> blocks = [{'confidence': 95.5}]
        >>> calculate_confidence(blocks)
        95.5
    """
    pass
```

### 代码格式化

使用Black自动格式化:

```bash
# 格式化所有代码
black backend/

# 检查格式
black backend/ --check

# 格式化特定文件
black backend/app.py
```

使用flake8检查:

```bash
# 检查代码
flake8 backend/

# 忽略某些错误
flake8 backend/ --ignore=E501,W503
```

## 调试技巧

### 使用日志

```python
import logging

logger = logging.getLogger(__name__)

def process_image(image_path):
    logger.debug(f"Processing image: {image_path}")
    
    try:
        result = do_processing(image_path)
        logger.info(f"Processed successfully: {len(result)} items")
        return result
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise
```

### 使用断点

```python
# Python内置调试器
import pdb

def problematic_function():
    x = 10
    pdb.set_trace()  # 在此处暂停
    y = x * 2
    return y

# IPython调试器(更强大)
from IPython import embed

def another_function():
    data = load_data()
    embed()  # 进入交互式shell
    return process(data)
```

### 性能分析

```python
# 使用装饰器计时
import time
from functools import wraps

def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} took {end - start:.2f}s")
        return result
    return wrapper

@timing_decorator
def slow_function():
    # 耗时操作
    pass
```

### 内存分析

```python
# 使用memory_profiler
from memory_profiler import profile

@profile
def memory_intensive_function():
    # 内存密集操作
    large_list = [i for i in range(1000000)]
    return sum(large_list)
```

## 扩展开发

### 添加新的OCR引擎

```python
# backend/ocr_engines/custom_engine.py
from backend.ocr_engine import OCREngine

class CustomOCREngine(OCREngine):
    def __init__(self, **kwargs):
        super().__init__()
        # 初始化自定义引擎
    
    def recognize(self, image_path):
        # 实现识别逻辑
        pass
```

### 添加新的导出格式

```python
# backend/document_composer.py
class DocumentComposer:
    def generate_pdf(self, task_data):
        """生成PDF文档"""
        from reportlab.pdfgen import canvas
        
        # PDF生成逻辑
        pass
    
    def generate_docx(self, task_data):
        """生成Word文档"""
        from docx import Document
        
        # DOCX生成逻辑
        pass
```

### 添加新的AI提供商

```python
# backend/ai_services/custom_provider.py
class CustomAIProvider:
    def __init__(self, api_key):
        self.api_key = api_key
    
    def correct_text(self, text):
        # 调用自定义AI服务
        pass
```

### 插件系统(计划)

```python
# backend/plugins/base.py
class PluginBase:
    def on_task_created(self, task_id):
        """任务创建时的钩子"""
        pass
    
    def on_ocr_completed(self, task_id, result):
        """OCR完成时的钩子"""
        pass
```

## 贡献代码

开发完成后:

1. 确保所有测试通过
2. 代码符合规范
3. 更新相关文档
4. 创建Pull Request

详见 [CONTRIBUTING.md](../CONTRIBUTING.md)

---

**最后更新**: 2026-10-27
