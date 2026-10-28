# 贡献指南 Contributing Guide

感谢您对古报纸OCR项目的关注！我们欢迎所有形式的贡献。

## 📋 目录

- [行为准则](#-行为准则)
- [如何贡献](#-如何贡献)
- [开发流程](#-开发流程)
- [代码规范](#-代码规范)
- [提交规范](#-提交规范)
- [Pull Request流程](#-pull-request流程)
- [问题报告](#-问题报告)

## 📜 行为准则

本项目遵循 [Contributor Covenant](https://www.contributor-covenant.org/) 行为准则。参与本项目即表示您同意遵守其条款。

### 我们的承诺

- 使用友好和包容的语言
- 尊重不同的观点和经验
- 优雅地接受建设性批评
- 关注对社区最有利的事情
- 对其他社区成员表示同理心

## 🤝 如何贡献

### 贡献类型

我们欢迎以下类型的贡献:

- 🐛 **Bug修复** - 修复已知问题
- ✨ **新功能** - 添加新特性
- 📝 **文档改进** - 改善文档质量
- 🎨 **UI/UX改进** - 改善用户界面和体验
- 🔧 **性能优化** - 提升系统性能
- ✅ **测试** - 添加或改进测试用例
- 🌐 **国际化** - 添加多语言支持

### 开始之前

1. ⭐ 给项目加星
2. 🍴 Fork项目到您的账号
3. 💬 查看 [Issues](https://github.com/ashaw36/NEWspaperocr/issues) 寻找可以参与的任务
4. 📢 如果您有新想法,先创建Issue讨论

## 🔄 开发流程

### 1. 设置开发环境

```bash
# 克隆您fork的仓库
git clone https://github.com/YOUR_USERNAME/NEWspaperocr.git
cd NEWspaperocr

# 添加上游仓库
git remote add upstream https://github.com/ashaw36/NEWspaperocr.git

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r backend/requirements.txt

# 安装开发依赖(如果有)
pip install -r backend/requirements-dev.txt  # 如果存在
```

### 2. 创建功能分支

```bash
# 更新主分支
git checkout main
git pull upstream main

# 创建新分支
git checkout -b feature/your-feature-name
# 或 bugfix/issue-number-description
```

### 3. 进行开发

- 编写代码
- 添加测试
- 更新文档
- 运行测试确保通过

### 4. 提交更改

```bash
# 添加更改的文件
git add <files>

# 提交(遵循提交规范)
git commit -m "feat: add new feature"

# 推送到您的fork
git push origin feature/your-feature-name
```

### 5. 创建Pull Request

1. 访问您fork的GitHub页面
2. 点击 "Pull Request" 按钮
3. 填写PR模板
4. 等待代码审查

## 💻 代码规范

### Python代码规范

我们遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/) 代码规范。

#### 基本规则

```python
# ✅ 好的示例
def process_ocr_result(image_path: str, options: dict) -> dict:
    """
    处理OCR识别结果
    
    Args:
        image_path: 图片路径
        options: 配置选项
        
    Returns:
        dict: 处理结果
    """
    # 使用4空格缩进
    result = {}
    
    # 变量名使用snake_case
    ocr_engine = OCREngine()
    
    # 常量使用大写
    MAX_RETRIES = 3
    
    return result


# ❌ 不好的示例
def processOCRResult(imagePath, options):  # 应使用snake_case
    result={}  # 运算符两侧应有空格
    ocrEngine = OCREngine()  # 应使用snake_case
    return result
```

#### 文档字符串

所有公共函数和类都应该有文档字符串:

```python
def calculate_confidence(text_blocks: list) -> float:
    """
    计算文本块的平均置信度
    
    此函数遍历所有文本块,计算置信度的加权平均值。
    
    Args:
        text_blocks (list): 文本块列表,每个块包含text和confidence字段
        
    Returns:
        float: 平均置信度,范围0-100
        
    Raises:
        ValueError: 如果text_blocks为空
        
    Example:
        >>> blocks = [{'text': '你好', 'confidence': 95.5}]
        >>> calculate_confidence(blocks)
        95.5
    """
    if not text_blocks:
        raise ValueError("text_blocks不能为空")
    
    total_conf = sum(block['confidence'] for block in text_blocks)
    return total_conf / len(text_blocks)
```

### JavaScript代码规范

```javascript
// ✅ 好的示例
function processApiResponse(response) {
    // 使用camelCase命名
    const taskId = response.task_id;
    const isCompleted = response.status === 'completed';
    
    // 使用const/let,不使用var
    const result = {
        id: taskId,
        completed: isCompleted
    };
    
    return result;
}

// ❌ 不好的示例
function process_api_response(response) {  // 应使用camelCase
    var task_id = response.task_id;  // 应使用const/let
    var is_completed = response.status === 'completed';
    return {id: task_id, completed: is_completed}  // 应有适当的格式化
}
```

### 代码检查

提交前请运行代码检查:

```bash
# Python代码检查
pip install flake8 black
flake8 backend/ --max-line-length=100
black backend/ --check

# 自动格式化
black backend/
```

## 📝 提交规范

我们使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范。

### 提交格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type类型

- `feat`: 新功能
- `fix`: Bug修复
- `docs`: 文档更新
- `style`: 代码格式(不影响代码运行的变动)
- `refactor`: 重构(既不是新功能也不是Bug修复)
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建过程或辅助工具的变动
- `ci`: CI/CD相关
- `build`: 构建系统或外部依赖的变动

### 示例

```bash
# 新功能
git commit -m "feat(ocr): add support for vertical text recognition"

# Bug修复
git commit -m "fix(api): correct task status update logic"

# 文档
git commit -m "docs(readme): update installation instructions"

# 重构
git commit -m "refactor(workflow): simplify task processing pipeline"

# 多行提交
git commit -m "feat(export): add PDF export support

- Implement PDF generation using PyMuPDF
- Add export button to UI
- Update API documentation

Closes #123"
```

### Scope范围

常用的scope包括:

- `ocr`: OCR相关
- `layout`: 版面分析
- `ai`: AI服务
- `api`: API接口
- `ui`: 用户界面
- `workflow`: 工作流
- `docs`: 文档
- `test`: 测试
- `config`: 配置

## 🔀 Pull Request流程

### PR标题

PR标题应该清晰描述更改内容:

```
feat(ocr): add vertical text recognition support
fix(api): resolve task status synchronization issue
docs(contributing): add code review guidelines
```

### PR描述模板

创建PR时请使用以下模板:

```markdown
## 📝 更改描述

简要描述此PR的目的和内容。

## 🔗 相关Issue

Closes #123
Related to #456

## ✨ 更改类型

- [ ] Bug修复
- [ ] 新功能
- [ ] 文档更新
- [ ] 性能优化
- [ ] 代码重构
- [ ] 其他 (请说明):

## 🧪 测试

描述您如何测试了这些更改:

- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 手动测试通过
- [ ] 添加了新的测试

## 📸 截图 (如果适用)

添加截图展示UI变化

## ✅ 检查清单

- [ ] 代码遵循项目的代码规范
- [ ] 已添加相关文档
- [ ] 已添加或更新测试
- [ ] 所有测试通过
- [ ] 提交信息遵循提交规范
- [ ] 已在本地测试这些更改

## 💭 其他信息

任何其他相关信息
```

### 代码审查

1. **响应及时**: 尽快回复审查意见
2. **保持礼貌**: 以建设性的方式讨论
3. **解释清楚**: 说明您的设计决策
4. **接受反馈**: 虚心接受改进建议
5. **更新及时**: 根据反馈及时更新代码

### 审查标准

PR将根据以下标准进行审查:

- ✅ 代码质量和可读性
- ✅ 是否遵循项目规范
- ✅ 测试覆盖率
- ✅ 文档完整性
- ✅ 性能影响
- ✅ 安全性考虑

## 🐛 问题报告

### 报告Bug

创建Bug报告时请包含:

1. **清晰的标题**: 简要描述问题
2. **环境信息**:
   - OS版本
   - Python版本
   - 依赖版本
3. **复现步骤**: 详细的复现步骤
4. **期望行为**: 您期望发生什么
5. **实际行为**: 实际发生了什么
6. **错误日志**: 相关的错误信息
7. **截图**: 如果适用

### Bug报告模板

```markdown
## 🐛 Bug描述

简要描述bug

## 🔄 复现步骤

1. 上传图片 '...'
2. 点击 '....'
3. 看到错误

## ✅ 期望行为

描述您期望发生什么

## ❌ 实际行为

描述实际发生了什么

## 🖥️ 环境信息

- OS: [e.g. Windows 11]
- Python版本: [e.g. 3.12.0]
- 浏览器: [e.g. Chrome 120]

## 📋 错误日志

```
粘贴相关错误日志
```

## 📸 截图

如果适用,添加截图
```

### 功能请求

创建功能请求时请包含:

1. **问题描述**: 您想解决什么问题
2. **建议方案**: 您的解决方案
3. **备选方案**: 其他可能的方案
4. **使用场景**: 具体的使用场景

## 🎯 开发任务

### Good First Issues

适合新贡献者的任务标记为 `good first issue`。这些任务:

- 范围明确
- 难度适中
- 有详细说明
- 适合了解项目

### Help Wanted

标记为 `help wanted` 的Issue特别需要社区帮助。

## 📚 资源

- [项目文档](./docs/)
- [API文档](./docs/API.md)
- [架构文档](./ARCHITECTURE.md)
- [开发指南](./docs/DEVELOPMENT.md)

## 💬 交流渠道

- GitHub Issues - 问题讨论
- GitHub Discussions - 一般性讨论
- Pull Request评论 - 代码审查

## 🙏 致谢

感谢所有贡献者对本项目的支持！

您的贡献将被记录在项目的Contributors列表中。

---

再次感谢您的贡献！让我们一起让古报纸OCR变得更好！ 🚀
