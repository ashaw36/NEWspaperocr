# API 接口文档

本文档详细描述了古报纸OCR系统的REST API接口。

## 📋 目录

- [基础信息](#基础信息)
- [任务管理](#任务管理)
- [OCR处理](#ocr处理)
- [AI服务](#ai服务)
- [导出功能](#导出功能)
- [错误处理](#错误处理)

## 基础信息

### Base URL

```
http://127.0.0.1:5000
```

### 内容类型

- 请求: `application/json` 或 `multipart/form-data`
- 响应: `application/json`

### 认证

当前版本不需要认证。生产环境部署时建议添加API密钥认证。

## 任务管理

### 创建任务

上传图片并创建新的OCR任务。

**请求**

```http
POST /api/tasks
Content-Type: multipart/form-data
```

**参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| file | File | 是 | 图片文件(PNG/JPG/PDF) |
| ai_layout | Boolean | 否 | 是否启用AI增强版面分析(默认: true) |

**响应**

```json
{
  "task_id": "f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o",
  "status": "pending",
  "created_at": "2026-10-27T10:30:00Z"
}
```

**cURL示例**

```bash
curl -X POST http://127.0.0.1:5000/api/tasks \
  -F "file=@newspaper.jpg" \
  -F "ai_layout=true"
```

---

### 查询任务状态

获取任务的当前状态和详细信息。

**请求**

```http
GET /api/tasks/{task_id}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | String | 任务ID |

**响应**

```json
{
  "task_id": "f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o",
  "status": "completed",
  "created_at": "2026-10-27T10:30:00Z",
  "updated_at": "2026-10-27T10:31:30Z",
  "steps": {
    "upload": "completed",
    "layout": "completed",
    "ocr": "completed",
    "correction": "completed",
    "validation": "completed"
  },
  "results": {
    "total_text_regions": 45,
    "total_characters": 2847,
    "average_confidence": 96.5,
    "articles_count": 8
  }
}
```

**状态说明**

| 状态 | 说明 |
|------|------|
| pending | 任务已创建,等待处理 |
| processing | 正在处理中 |
| completed | 处理完成 |
| failed | 处理失败 |

**cURL示例**

```bash
curl -X GET http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o
```

---

### 列出所有任务

获取所有任务列表(可选功能)。

**请求**

```http
GET /api/tasks
```

**查询参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| limit | Integer | 否 | 返回数量限制(默认: 10) |
| offset | Integer | 否 | 偏移量(默认: 0) |
| status | String | 否 | 按状态过滤 |

**响应**

```json
{
  "tasks": [
    {
      "task_id": "...",
      "status": "completed",
      "created_at": "..."
    }
  ],
  "total": 25,
  "limit": 10,
  "offset": 0
}
```

---

## OCR处理

### 启动OCR识别

对上传的图片执行OCR识别。

**请求**

```http
POST /api/tasks/{task_id}/ocr
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | String | 任务ID |

**响应**

```json
{
  "status": "processing",
  "message": "OCR识别已启动"
}
```

完成后,任务状态将更新为 `completed`,OCR结果将包含在任务详情中。

**cURL示例**

```bash
curl -X POST http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/ocr
```

---

### 获取OCR结果

获取原始OCR识别结果。

**请求**

```http
GET /api/tasks/{task_id}/ocr/result
```

**响应**

```json
{
  "text_blocks": [
    {
      "text": "北平新組織成立說",
      "confidence": 98.5,
      "bbox": [100, 50, 300, 80],
      "type": "title"
    },
    {
      "text": "南京失守以後华北即将有新组织报告...",
      "confidence": 96.2,
      "bbox": [100, 90, 300, 500],
      "type": "body"
    }
  ],
  "statistics": {
    "total_blocks": 45,
    "total_characters": 2847,
    "average_confidence": 96.5
  }
}
```

---

## AI服务

### 启动AI校正

使用AI对OCR结果进行校正和文章聚合。

**请求**

```http
POST /api/tasks/{task_id}/correction
```

**请求体(可选)**

```json
{
  "enable_article_aggregation": true,
  "confidence_threshold": 90.0
}
```

**响应**

```json
{
  "status": "processing",
  "message": "AI校正已启动"
}
```

**cURL示例**

```bash
curl -X POST http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/correction \
  -H "Content-Type: application/json" \
  -d '{"enable_article_aggregation": true}'
```

---

### 生成AI总结

基于识别结果生成内容总结或回答问题。

**请求**

```http
POST /api/tasks/{task_id}/analysis
```

**请求体**

```json
{
  "action": "summary",
  "instruction": "请总结报纸的主要内容"
}
```

**参数**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| action | String | 是 | 操作类型: `summary`(总结) 或 `question`(问答) |
| instruction | String | 是 | 总结指令或问题内容 |

**响应**

```json
{
  "status": "completed",
  "result": {
    "summary": "本期报纸主要报道了...",
    "key_points": [
      "北平新组织成立",
      "南京失守后的局势分析",
      "经济政策调整"
    ]
  }
}
```

**action类型说明**

- `summary`: 生成内容总结
- `question`: 回答关于内容的问题

**cURL示例**

```bash
curl -X POST http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/analysis \
  -H "Content-Type: application/json" \
  -d '{"action": "summary", "instruction": "请总结主要内容"}'
```

---

## 质量验证

### 执行质量验证

验证识别结果的完整性和准确性。

**请求**

```http
GET /api/tasks/{task_id}/validate
```

**响应**

```json
{
  "overall_score": 96.5,
  "passed": true,
  "completeness": {
    "score": 98.5,
    "passed": true,
    "details": "所有文字区域均被识别"
  },
  "accuracy": {
    "score": 97.3,
    "passed": true,
    "average_confidence": 96.5,
    "high_quality_ratio": 0.933
  },
  "layout_quality": {
    "score": 95.8,
    "passed": true,
    "ai_enhanced": true
  },
  "article_aggregation": {
    "score": 92.0,
    "passed": true,
    "articles_count": 8,
    "cross_region_articles": 3
  },
  "suggestions": [
    "3个文章跨越多个区域,建议人工复核"
  ]
}
```

**cURL示例**

```bash
curl -X GET http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/validate
```

---

## 导出功能

### 导出文档

导出识别结果为指定格式。

**请求**

```http
GET /api/tasks/{task_id}/export/{format}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | String | 任务ID |
| format | String | 导出格式: `markdown`, `html`, `json`, `raw`, `corrected` |

**格式说明**

| 格式 | 说明 | Content-Type |
|------|------|--------------|
| markdown | Markdown文档 | text/markdown |
| html | HTML文档 | text/html |
| json | JSON数据 | application/json |
| raw | 原始OCR文本 | text/plain |
| corrected | AI校正后文本 | text/plain |

**Markdown响应示例**

```markdown
# 民国日报

> OCR识别时间: 2026-10-27 10:30:00
> 总页数: 1
> 识别引擎: RapidOCR + AI增强

## 📰 识别的文章

### 1. 北平新組織成立說

南京失守以後华北即将有新组织报告...

*[置信度: 96.5%, 页码: 1]*

---

## 📊 识别质量报告

- **总字符数**: 2847
- **平均置信度**: 96.5%
- **高质量区域**: 42/45 (93.3%)
```

**JSON响应示例**

```json
{
  "metadata": {
    "task_id": "f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o",
    "created_at": "2026-10-27T10:30:00Z",
    "processed_at": "2026-10-27T10:31:30Z"
  },
  "articles": [
    {
      "id": 1,
      "title": "北平新組織成立說",
      "content": "南京失守以後...",
      "confidence": 96.5,
      "page": 1
    }
  ],
  "statistics": {
    "total_characters": 2847,
    "average_confidence": 96.5,
    "articles_count": 8
  }
}
```

**cURL示例**

```bash
# 导出Markdown
curl -X GET http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/export/markdown \
  -o result.md

# 导出HTML
curl -X GET http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/export/html \
  -o result.html

# 导出JSON
curl -X GET http://127.0.0.1:5000/api/tasks/f7c3a1b2-4d5e-6f7g-8h9i-0j1k2l3m4n5o/export/json \
  -o result.json
```

---

## 错误处理

### 错误响应格式

所有错误响应遵循统一格式:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "details": "详细错误信息(可选)"
  }
}
```

### HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 资源创建成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | 服务暂时不可用 |

### 常见错误码

| 错误码 | 说明 | HTTP状态码 |
|--------|------|------------|
| TASK_NOT_FOUND | 任务不存在 | 404 |
| INVALID_FILE_TYPE | 不支持的文件类型 | 400 |
| FILE_TOO_LARGE | 文件过大 | 400 |
| OCR_FAILED | OCR识别失败 | 500 |
| AI_SERVICE_ERROR | AI服务错误 | 500 |
| INVALID_PARAMETERS | 参数错误 | 400 |

### 错误示例

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "任务不存在",
    "details": "Task ID 'abc123' not found in database"
  }
}
```

---

## 速率限制

当前版本没有速率限制。生产环境建议配置:

- 每IP: 100请求/分钟
- 每API密钥: 1000请求/小时

超过限制时返回:

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "请求过于频繁,请稍后重试",
    "retry_after": 60
  }
}
```

HTTP状态码: `429 Too Many Requests`

---

## Webhooks (计划功能)

未来版本将支持Webhook通知,在任务状态变化时主动推送:

```http
POST https://your-domain.com/webhook
Content-Type: application/json

{
  "event": "task.completed",
  "task_id": "...",
  "timestamp": "2026-10-27T10:31:30Z",
  "data": {
    "status": "completed",
    "results": {...}
  }
}
```

---

## SDK支持

### Python SDK (示例)

```python
from newspaper_ocr_client import OCRClient

client = OCRClient(base_url="http://127.0.0.1:5000")

# 创建任务
task = client.create_task("newspaper.jpg", ai_layout=True)

# 等待完成
task.wait_for_completion()

# 导出结果
markdown = task.export("markdown")
print(markdown)
```

### JavaScript SDK (示例)

```javascript
const OCRClient = require('newspaper-ocr-client');

const client = new OCRClient('http://127.0.0.1:5000');

// 创建任务
const task = await client.createTask('newspaper.jpg', { aiLayout: true });

// 等待完成
await task.waitForCompletion();

// 导出结果
const markdown = await task.export('markdown');
console.log(markdown);
```

---

## 更新日志

### v1.0.0 (2026-10-27)

- 初始API版本发布
- 支持基础OCR识别
- 支持AI增强校正
- 支持多格式导出
- 支持质量验证

---

## 技术支持

- 📖 查看 [故障排除文档](./TROUBLESHOOTING.md)
- 💬 提交 [GitHub Issue](https://github.com/ashaw36/NEWspaperocr/issues)
- 📧 发送邮件反馈

---

**最后更新**: 2026-10-27
