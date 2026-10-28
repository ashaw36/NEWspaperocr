# 故障排除指南 Troubleshooting Guide

本文档提供古报纸OCR系统常见问题的解决方案。

## 📋 目录

- [安装问题](#安装问题)
- [运行时问题](#运行时问题)
- [OCR识别问题](#ocr识别问题)
- [AI服务问题](#ai服务问题)
- [性能问题](#性能问题)
- [网络问题](#网络问题)
- [数据问题](#数据问题)

## 安装问题

### Python版本不兼容

**症状**: 安装依赖时报错 `requires python >=3.12`

**解决方案**:

```bash
# 检查Python版本
python --version

# 如果版本低于3.12,请安装新版本
# Windows: 从 python.org 下载安装
# Ubuntu:
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv
```

---

### pip安装依赖失败

**症状**: `pip install -r requirements.txt` 失败

**可能原因和解决方案**:

1. **网络问题**

```bash
# 使用国内镜像源
pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

2. **缺少编译工具**

```bash
# Windows: 安装 Visual Studio Build Tools
# 下载: https://visualstudio.microsoft.com/visual-cpp-build-tools/

# Ubuntu:
sudo apt install build-essential python3-dev
```

3. **权限问题**

```bash
# 使用虚拟环境(推荐)
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux

# 或使用 --user 标志
pip install --user -r backend/requirements.txt
```

---

### OpenCV导入失败

**症状**: `ImportError: libGL.so.1: cannot open shared object file`

**解决方案**:

```bash
# Ubuntu/Debian
sudo apt install libgl1-mesa-glx libglib2.0-0

# 或使用headless版本
pip uninstall opencv-python
pip install opencv-python-headless
```

---

## 运行时问题

### 应用无法启动

**症状**: `python backend/app.py` 报错

**检查步骤**:

1. **检查端口占用**

```bash
# Windows
netstat -ano | findstr :5000

# Linux
lsof -i :5000

# 如果端口被占用,关闭占用进程或更改端口
# 修改 backend/app.py 中的端口号
app.run(host='0.0.0.0', port=5001)
```

2. **检查虚拟环境**

```bash
# 确认在虚拟环境中
which python  # Linux
where python  # Windows

# 应该指向 .venv/bin/python 或 .venv\Scripts\python.exe
```

3. **检查依赖完整性**

```bash
pip check
pip install --upgrade -r backend/requirements.txt
```

---

### Flask应用崩溃

**症状**: 应用运行一段时间后崩溃

**解决方案**:

1. **查看错误日志**

```bash
# 检查应用日志
tail -f /var/log/ocr-app/error.log

# 或在代码中添加详细日志
import logging
logging.basicConfig(level=logging.DEBUG)
```

2. **内存不足**

```bash
# 检查内存使用
free -h  # Linux
# 清理临时文件
rm -rf data/tasks/*/upload/*

# 增加swap空间(Linux)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

3. **线程/进程问题**

```python
# 减少worker数量
# gunicorn_config.py
workers = 2  # 减少worker数量
timeout = 600  # 增加超时时间
```

---

### 文件上传失败

**症状**: 上传大文件时返回 `413 Request Entity Too Large`

**解决方案**:

1. **Flask配置**

```python
# backend/app.py
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
```

2. **Nginx配置**

```nginx
# /etc/nginx/sites-available/ocr-app
client_max_body_size 100M;
```

3. **Gunicorn配置**

```python
# gunicorn_config.py
timeout = 300  # 增加超时时间
worker_class = 'sync'
```

---

## OCR识别问题

### 识别准确率低

**症状**: OCR识别结果不准确,错误率高

**解决方案**:

1. **提高图片质量**

```python
# 图片预处理
from PIL import Image
import cv2
import numpy as np

def preprocess_image(image_path):
    # 读取图片
    img = cv2.imread(image_path)
    
    # 转灰度
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 去噪
    denoised = cv2.fastNlMeansDenoising(gray)
    
    # 二值化
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 倾斜校正
    # ... 添加倾斜检测和校正代码
    
    return binary
```

2. **调整OCR参数**

```python
# backend/ocr_engine.py
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR(
    text_score=0.6,  # 降低文本置信度阈值
    use_angle_cls=True,  # 启用方向分类
    use_text_det=True,  # 启用文本检测
)
```

3. **使用AI校正**

确保启用AI校正功能来修正OCR错误。

---

### 竖排文字识别失败

**症状**: 竖排文字识别为乱码

**解决方案**:

```python
# 确保启用方向分类
ocr = RapidOCR(use_angle_cls=True)

# 或在版面分析时标记文字方向
# backend/layout_engine.py
region['text_direction'] = 'vertical'  # 或 'horizontal'
```

---

### 识别速度慢

**症状**: OCR识别耗时过长

**解决方案**:

1. **降低图片分辨率**

```python
from PIL import Image

def resize_image(image_path, max_size=2000):
    img = Image.open(image_path)
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        img.save(image_path)
```

2. **使用GPU加速**

```bash
# 安装CUDA版本的ONNX Runtime
pip uninstall onnxruntime
pip install onnxruntime-gpu

# 检查GPU是否可用
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

3. **批量处理优化**

```python
# 调整批处理大小
batch_size = 4  # 根据内存大小调整
```

---

### 识别结果为空

**症状**: OCR返回空结果或没有识别到文字

**检查步骤**:

1. **检查图片格式和质量**

```bash
# 检查图片信息
file image.jpg
identify -verbose image.jpg  # 需要 ImageMagick

# 确保图片:
# - 格式正确 (JPG/PNG)
# - 分辨率足够 (建议 >= 300 DPI)
# - 文件未损坏
```

2. **检查图片对比度**

```python
# 增强对比度
from PIL import Image, ImageEnhance

img = Image.open('image.jpg')
enhancer = ImageEnhance.Contrast(img)
img = enhancer.enhance(2.0)  # 增强对比度
img.save('enhanced.jpg')
```

3. **检查OCR引擎状态**

```python
# 测试OCR引擎
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
result, elapse = ocr('test_image.jpg')
print(f"Result: {result}")
print(f"Time: {elapse}s")
```

---

## AI服务问题

### AI服务不可用

**症状**: AI校正或总结功能报错

**解决方案**:

1. **检查API密钥**

```bash
# 检查 .env 文件
cat backend/.env | grep API_KEY

# 确保密钥正确且未过期
```

2. **检查网络连接**

```bash
# 测试API连接
curl -I https://api.anthropic.com
curl -I https://api.openai.com
```

3. **检查API额度**

访问对应的API平台检查:
- 额度是否用完
- 账户是否被封禁
- 支付信息是否有效

4. **使用重试机制**

```python
# backend/ai_service.py
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_ai_service(prompt):
    # AI调用代码
    pass
```

---

### AI响应超时

**症状**: AI请求长时间无响应

**解决方案**:

```python
# 增加超时设置
import anthropic

client = anthropic.Anthropic(
    api_key=api_key,
    timeout=60.0,  # 60秒超时
)

# 或使用异步方式
import asyncio
async def call_ai_async():
    # 异步AI调用
    pass
```

---

### AI返回结果不理想

**症状**: AI生成的总结或校正质量差

**解决方案**:

1. **优化提示词**

```python
# 更详细的指令
prompt = """
请分析以下古报纸OCR识别结果,并:
1. 修正明显的OCR错误
2. 识别文章边界
3. 聚合跨栏文章
4. 保持原文语言风格

OCR结果:
{ocr_text}
"""
```

2. **调整模型参数**

```python
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=4000,  # 增加token限制
    temperature=0.3,  # 降低随机性
    messages=[...]
)
```

---

## 性能问题

### 内存使用过高

**症状**: 系统内存占用持续增长

**解决方案**:

1. **清理临时文件**

```python
# 定期清理旧任务
import shutil
import time

def cleanup_old_tasks(days=7):
    tasks_dir = 'data/tasks'
    now = time.time()
    cutoff = now - (days * 86400)
    
    for task_id in os.listdir(tasks_dir):
        task_path = os.path.join(tasks_dir, task_id)
        if os.path.getmtime(task_path) < cutoff:
            shutil.rmtree(task_path)
```

2. **优化图片加载**

```python
# 使用生成器而不是一次性加载
def process_images_generator(image_paths):
    for path in image_paths:
        img = load_image(path)
        yield process(img)
        del img  # 显式释放内存
```

3. **限制并发请求**

```python
# 使用信号量限制并发
from threading import Semaphore

max_concurrent = 4
semaphore = Semaphore(max_concurrent)

def process_task(task_id):
    with semaphore:
        # 处理任务
        pass
```

---

### CPU使用率过高

**症状**: CPU持续满载

**解决方案**:

1. **减少worker数量**

```python
# gunicorn_config.py
workers = 2  # 降低worker数量
```

2. **使用进程池**

```python
from multiprocessing import Pool

def process_batch(images):
    with Pool(processes=4) as pool:
        results = pool.map(ocr_process, images)
    return results
```

3. **添加任务队列**

```bash
# 使用Celery异步处理
pip install celery redis

# 配置Celery
# backend/celery_config.py
from celery import Celery

app = Celery('tasks', broker='redis://localhost:6379/0')
```

---

### 磁盘空间不足

**症状**: 磁盘空间被任务数据占满

**解决方案**:

```bash
# 检查磁盘使用
df -h

# 找出大文件
du -sh data/tasks/* | sort -h | tail -10

# 清理旧任务数据
find data/tasks -type f -mtime +7 -delete

# 压缩旧任务
find data/tasks -type d -mtime +7 -exec tar -czf {}.tar.gz {} \; -exec rm -rf {} \;
```

---

## 网络问题

### 无法访问Web界面

**症状**: 浏览器无法打开应用

**检查步骤**:

1. **检查服务状态**

```bash
# 检查应用是否运行
ps aux | grep python
ps aux | grep gunicorn

# 检查端口监听
netstat -tuln | grep 5000
```

2. **检查防火墙**

```bash
# Ubuntu UFW
sudo ufw status
sudo ufw allow 5000

# CentOS firewalld
sudo firewall-cmd --list-all
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

3. **检查Nginx配置**

```bash
# 测试配置
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx

# 查看错误日志
sudo tail -f /var/log/nginx/error.log
```

---

### CORS错误

**症状**: 浏览器控制台显示CORS错误

**解决方案**:

```python
# backend/app.py
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5000", "https://your-domain.com"],
        "methods": ["GET", "POST"],
        "allow_headers": ["Content-Type"]
    }
})
```

---

## 数据问题

### 任务数据丢失

**症状**: 找不到之前的任务数据

**解决方案**:

1. **检查数据目录**

```bash
# 确认数据目录位置
ls -la data/tasks/

# 检查权限
ls -la data/
```

2. **恢复备份**

```bash
# 从备份恢复
tar -xzf /backup/ocr-app/data_20261027.tar.gz -C .
```

3. **修复数据库**(如果使用)

```bash
# SQLite修复
sqlite3 data/tasks.db ".dump" | sqlite3 data/tasks_new.db
mv data/tasks_new.db data/tasks.db
```

---

### JSON解析错误

**症状**: `JSONDecodeError: Expecting value`

**解决方案**:

```python
# 添加错误处理
import json

def safe_load_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        # 尝试修复或返回默认值
        return {}
    except FileNotFoundError:
        print(f"文件不存在: {file_path}")
        return {}
```

---

## 调试技巧

### 启用详细日志

```python
# backend/app.py
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler()
    ]
)
```

### 使用Python调试器

```python
# 在代码中设置断点
import pdb; pdb.set_trace()

# 或使用 IPython
from IPython import embed; embed()
```

### 性能分析

```python
# 使用cProfile
python -m cProfile -o output.prof backend/app.py

# 分析结果
python -m pstats output.prof
```

---

## 获取帮助

如果以上方案无法解决您的问题:

1. 📖 查看完整文档: [README.md](../README.md)
2. 🔍 搜索现有Issues: [GitHub Issues](https://github.com/ashaw36/NEWspaperocr/issues)
3. 💬 创建新Issue并提供:
   - 错误信息完整日志
   - 系统环境信息
   - 复现步骤
   - 已尝试的解决方案

---

**最后更新**: 2026-10-27
