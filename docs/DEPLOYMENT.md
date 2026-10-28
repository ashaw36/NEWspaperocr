# 部署指南 Deployment Guide

本文档介绍如何将古报纸OCR系统部署到生产环境。

## 📋 目录

- [部署前准备](#部署前准备)
- [Windows部署](#windows部署)
- [Linux部署](#linux部署)
- [Docker部署](#docker部署-计划中)
- [云平台部署](#云平台部署)
- [性能优化](#性能优化)
- [监控和日志](#监控和日志)
- [备份和恢复](#备份和恢复)

## 部署前准备

### 系统要求

#### 最低配置

- **CPU**: 2核
- **内存**: 4GB RAM
- **磁盘**: 10GB可用空间
- **操作系统**: Windows 10+, Ubuntu 20.04+, CentOS 7+

#### 推荐配置

- **CPU**: 4核或更多
- **内存**: 8GB RAM或更多
- **磁盘**: 50GB SSD
- **GPU**: NVIDIA GPU (可选,用于加速OCR)
- **网络**: 稳定的互联网连接(用于AI服务)

### 软件依赖

- Python 3.12 或更高版本
- pip 包管理器
- Git (用于代码部署)

### 安全检查清单

- [ ] 更改默认配置
- [ ] 配置防火墙规则
- [ ] 设置文件上传大小限制
- [ ] 配置HTTPS (生产环境)
- [ ] 启用API密钥认证 (如需要)
- [ ] 配置日志轮转
- [ ] 设置数据备份策略

## Windows部署

### 1. 环境准备

```powershell
# 检查Python版本
python --version  # 应该 >= 3.12

# 克隆项目
git clone https://github.com/ashaw36/NEWspaperocr.git
cd NEWspaperocr

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate
```

### 2. 安装依赖

```powershell
# 升级pip
python -m pip install --upgrade pip

# 安装项目依赖
pip install -r backend/requirements.txt

# (可选) 安装生产环境依赖
pip install gunicorn  # 仅Linux支持
```

### 3. 配置应用

```powershell
# 复制配置文件
copy backend\.env.example backend\.env

# 编辑配置文件
notepad backend\.env
```

配置项说明:

```env
# AI服务配置
ANTHROPIC_API_KEY=your_api_key_here
OPENAI_API_KEY=your_api_key_here

# 应用配置
FLASK_ENV=production
FLASK_DEBUG=0
MAX_CONTENT_LENGTH=104857600  # 100MB

# 数据目录
DATA_DIR=./data
UPLOAD_DIR=./data/uploads
```

### 4. 使用Windows服务运行

创建 `run_service.py`:

```python
import os
import sys

# 设置工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 激活虚拟环境
activate_this = os.path.join('.venv', 'Scripts', 'activate_this.py')
exec(open(activate_this).read(), {'__file__': activate_this})

# 启动应用
from backend.app import app
app.run(host='0.0.0.0', port=5000)
```

使用NSSM (Non-Sucking Service Manager) 创建Windows服务:

```powershell
# 下载NSSM: https://nssm.cc/download
# 安装服务
nssm install NewspaperOCR "C:\Path\To\Python\python.exe" "C:\Path\To\Project\run_service.py"

# 启动服务
nssm start NewspaperOCR

# 查看状态
nssm status NewspaperOCR
```

### 5. 配置IIS反向代理 (可选)

在IIS中安装 URL Rewrite 和 Application Request Routing 模块。

`web.config`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Reverse Proxy" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://localhost:5000/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

## Linux部署

### 1. 环境准备

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y  # Ubuntu/Debian
# sudo yum update -y  # CentOS/RHEL

# 安装Python 3.12
sudo apt install python3.12 python3.12-venv python3-pip -y

# 安装其他依赖
sudo apt install git nginx supervisor -y
```

### 2. 创建应用用户

```bash
# 创建专用用户
sudo useradd -m -s /bin/bash ocr-app

# 切换用户
sudo su - ocr-app
```

### 3. 部署应用

```bash
# 克隆项目
git clone https://github.com/ashaw36/NEWspaperocr.git
cd NEWspaperocr

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r backend/requirements.txt
pip install gunicorn  # WSGI服务器

# 配置环境变量
cp backend/.env.example backend/.env
nano backend/.env
```

### 4. 使用Gunicorn运行

创建 `gunicorn_config.py`:

```python
# Gunicorn配置文件
bind = "127.0.0.1:5000"
workers = 4  # CPU核心数 * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 300  # 超时时间(秒)
keepalive = 2

# 日志
accesslog = "/var/log/ocr-app/access.log"
errorlog = "/var/log/ocr-app/error.log"
loglevel = "info"

# 进程
daemon = False
pidfile = "/var/run/ocr-app/gunicorn.pid"
```

测试运行:

```bash
gunicorn -c gunicorn_config.py backend.app:app
```

### 5. 使用Supervisor管理进程

创建 `/etc/supervisor/conf.d/ocr-app.conf`:

```ini
[program:ocr-app]
command=/home/ocr-app/NEWspaperocr/.venv/bin/gunicorn -c gunicorn_config.py backend.app:app
directory=/home/ocr-app/NEWspaperocr
user=ocr-app
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/ocr-app/app.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="/home/ocr-app/NEWspaperocr/.venv/bin"
```

启动服务:

```bash
# 创建日志目录
sudo mkdir -p /var/log/ocr-app
sudo chown ocr-app:ocr-app /var/log/ocr-app

# 创建PID目录
sudo mkdir -p /var/run/ocr-app
sudo chown ocr-app:ocr-app /var/run/ocr-app

# 重新加载Supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start ocr-app

# 查看状态
sudo supervisorctl status ocr-app
```

### 6. 配置Nginx反向代理

创建 `/etc/nginx/sites-available/ocr-app`:

```nginx
upstream ocr_backend {
    server 127.0.0.1:5000;
}

server {
    listen 80;
    server_name your-domain.com;
    
    client_max_body_size 100M;
    
    # 静态文件
    location /static {
        alias /home/ocr-app/NEWspaperocr/frontend;
        expires 30d;
    }
    
    # API和动态内容
    location / {
        proxy_pass http://ocr_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }
}
```

启用站点:

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/ocr-app /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx
```

### 7. 配置HTTPS (Let's Encrypt)

```bash
# 安装Certbot
sudo apt install certbot python3-certbot-nginx -y

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo certbot renew --dry-run
```

## Docker部署 (计划中)

> 注意: Docker支持正在开发中,以下为规划配置。

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY backend/requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 创建数据目录
RUN mkdir -p /app/data/tasks

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn_config.py", "backend.app:app"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  ocr-app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/app/data
      - ./logs:/var/log/ocr-app
    restart: unless-stopped
    
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend:/usr/share/nginx/html:ro
    depends_on:
      - ocr-app
    restart: unless-stopped
```

## 云平台部署

### AWS部署

#### EC2部署

1. 创建EC2实例 (推荐 t3.medium 或更高)
2. 配置安全组:
   - 入站规则: 80 (HTTP), 443 (HTTPS), 22 (SSH)
3. 连接实例并按照Linux部署步骤操作

#### Elastic Beanstalk部署 (计划支持)

```bash
# 安装EB CLI
pip install awsebcli

# 初始化
eb init -p python-3.12 newspaper-ocr

# 创建环境
eb create production-env

# 部署
eb deploy
```

### Azure部署

#### Azure App Service

1. 创建App Service (Python 3.12)
2. 配置环境变量
3. 使用Git或ZIP部署

```bash
# 使用Azure CLI
az webapp up --name newspaper-ocr --resource-group MyResourceGroup
```

### Google Cloud Platform

#### App Engine

`app.yaml`:

```yaml
runtime: python312
entrypoint: gunicorn -b :$PORT backend.app:app

instance_class: F4

automatic_scaling:
  min_instances: 1
  max_instances: 10
```

部署:

```bash
gcloud app deploy
```

## 性能优化

### 1. 应用层优化

```python
# backend/config.py
class ProductionConfig:
    # 缓存配置
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = 'redis://localhost:6379/0'
    
    # 并发配置
    MAX_WORKERS = 4
    
    # OCR优化
    OCR_USE_GPU = True  # 如果有GPU
    OCR_BATCH_SIZE = 8
```

### 2. 数据库优化

```bash
# 如果使用Redis缓存
sudo apt install redis-server
pip install redis flask-caching

# 配置Redis
sudo nano /etc/redis/redis.conf
# 设置 maxmemory 和 maxmemory-policy
```

### 3. 文件系统优化

```bash
# 使用tmpfs存储临时文件
sudo mount -t tmpfs -o size=2G tmpfs /tmp/ocr-temp

# 添加到 /etc/fstab
tmpfs /tmp/ocr-temp tmpfs size=2G 0 0
```

### 4. Nginx优化

```nginx
# 启用gzip压缩
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript text/xml;

# 启用缓存
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=ocr_cache:10m max_size=1g;

location /api/ {
    proxy_cache ocr_cache;
    proxy_cache_valid 200 5m;
}
```

## 监控和日志

### 1. 日志配置

```python
# backend/logging_config.py
LOGGING_CONFIG = {
    'version': 1,
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/ocr-app/app.log',
            'maxBytes': 50 * 1024 * 1024,  # 50MB
            'backupCount': 10,
            'formatter': 'detailed',
        },
    },
    'formatters': {
        'detailed': {
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
        },
    },
    'loggers': {
        'app': {
            'handlers': ['file'],
            'level': 'INFO',
        },
    },
}
```

### 2. 性能监控

安装监控工具:

```bash
# Prometheus + Grafana
pip install prometheus-flask-exporter

# 在应用中启用
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)
```

### 3. 错误追踪

```bash
# Sentry集成
pip install sentry-sdk[flask]
```

```python
# backend/app.py
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(
    dsn="your-sentry-dsn",
    integrations=[FlaskIntegration()],
)
```

## 备份和恢复

### 1. 自动备份脚本

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/ocr-app"
DATA_DIR="/home/ocr-app/NEWspaperocr/data"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份
tar -czf "$BACKUP_DIR/data_$DATE.tar.gz" "$DATA_DIR"

# 保留最近7天的备份
find "$BACKUP_DIR" -name "data_*.tar.gz" -mtime +7 -delete
```

添加到crontab:

```bash
# 每天凌晨2点备份
0 2 * * * /home/ocr-app/backup.sh
```

### 2. 恢复数据

```bash
# 停止服务
sudo supervisorctl stop ocr-app

# 恢复数据
tar -xzf /backup/ocr-app/data_20261027_020000.tar.gz -C /home/ocr-app/NEWspaperocr/

# 启动服务
sudo supervisorctl start ocr-app
```

## 安全加固

### 1. 防火墙配置

```bash
# Ubuntu UFW
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# CentOS firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 2. 文件权限

```bash
# 设置正确的文件权限
chmod 750 /home/ocr-app/NEWspaperocr
chmod 640 /home/ocr-app/NEWspaperocr/backend/.env
chown -R ocr-app:ocr-app /home/ocr-app/NEWspaperocr
```

### 3. 限制资源使用

```bash
# 使用systemd限制
sudo nano /etc/systemd/system/ocr-app.service
```

```ini
[Service]
MemoryLimit=4G
CPUQuota=200%
```

## 故障排查

常见问题请参考 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

---

## 检查清单

部署完成后,请验证:

- [ ] 应用正常启动
- [ ] 可以访问Web界面
- [ ] 可以上传和处理图片
- [ ] OCR识别功能正常
- [ ] AI服务正常(如果配置)
- [ ] 日志正常写入
- [ ] HTTPS证书有效
- [ ] 备份脚本正常运行
- [ ] 监控指标正常显示

---

**最后更新**: 2026-10-27
