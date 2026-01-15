# Cookie 自动检测和 Webhook 通知功能

## 功能概述

本功能为微博 Cookie 管理系统添加了自动检测和 Webhook 通知能力，当 Cookie 失效时会自动触发 Webhook 通知。

### 主要特性

1. **自动定时检测**：支持通过 cron 表达式配置定时检测所有 Cookie Bundle
2. **Webhook 通知**：Cookie 失效时自动发送 HTTP POST 请求到指定的 Webhook URL
3. **可配置的通知内容**：支持自定义 Webhook 消息模板和请求头
4. **手动触发**：支持手动触发检测任务进行测试
5. **状态追踪**：记录每个 Cookie 的检测状态和最后检测时间

## 配置说明

### 环境变量配置

在 `.env` 文件中添加以下配置：

```bash
# Cookie 自动检测配置
COOKIE_CHECK_SCHEDULE_CONFIG_KEY=weibo:cookie:schedule:config
COOKIE_CHECK_SCHEDULE_LOCK_KEY=weibo:cookie:schedule:lock
WEBHOOK_CONFIG_KEY=weibo:webhook:config
```

**配置项说明**：

- `COOKIE_CHECK_SCHEDULE_CONFIG_KEY`：Redis 中存储定时任务配置的键名
- `COOKIE_CHECK_SCHEDULE_LOCK_KEY`：Redis 分布式锁键名，防止重复执行
- `WEBHOOK_CONFIG_KEY`：Redis 中存储 Webhook 配置的键名

### Webhook 配置

Webhook 配置通过 API 进行管理，存储在 Redis 中，包含以下字段：

```json
{
  "enabled": true,
  "webhook_url": "https://your-webhook-url.com/notify",
  "message_template": "{\"event\":\"cookie_validation_failed\",\"cookie_name\":\"{cookie_name}\",\"status\":\"{status}\",\"reason\":\"{reason}\",\"timestamp\":\"{timestamp}\"}",
  "timeout": 10,
  "custom_headers": "{\"Authorization\":\"Bearer your-token\"}",
  "updated_at": "2026-01-13 10:00:00"
}
```

**字段说明**：

- `enabled`：是否启用 Webhook 通知（true/false）
- `webhook_url`：Webhook 接收地址（必填）
- `message_template`：消息模板（JSON 格式字符串），支持变量替换
- `timeout`：请求超时时间（秒），范围 1-60
- `custom_headers`：自定义 HTTP 请求头（JSON 格式字符串）
- `updated_at`：最后更新时间

**消息模板变量**：

- `{cookie_name}`：Cookie Bundle 名称
- `{status}`：Cookie 状态（ok/expired/error）
- `{reason}`：失败原因
- `{timestamp}`：检测时间

### 定时任务配置

定时任务配置存储在 Redis 中，包含以下字段：

```json
{
  "enabled": true,
  "cron_expression": "0 * * * *",
  "last_run_time": "2026-01-13 10:00:00",
  "next_run_time": ""
}
```

**字段说明**：

- `enabled`：是否启用定时检测（true/false）
- `cron_expression`：Cron 表达式，格式为 `分 时 日 月 周`
  - 示例：`0 * * * *` 表示每小时整点执行
  - 示例：`0 */2 * * *` 表示每 2 小时执行
  - 示例：`0 0 * * *` 表示每天凌晨执行
- `last_run_time`：最后一次执行时间
- `next_run_time`：下次执行时间（预留字段）

## API 接口说明

### Webhook 配置管理

#### 1. 获取 Webhook 配置

**请求**：
```http
GET /weibo/api/webhook/config
```

**响应**：
```json
{
  "success": true,
  "config": {
    "enabled": false,
    "webhook_url": "",
    "message_template": "{\"event\":\"cookie_validation_failed\",\"cookie_name\":\"{cookie_name}\",\"status\":\"{status}\",\"reason\":\"{reason}\",\"timestamp\":\"{timestamp}\"}",
    "timeout": 10,
    "custom_headers": "{}"
  }
}
```

#### 2. 更新 Webhook 配置

**请求**：
```http
PUT /weibo/api/webhook/config
Content-Type: application/json

{
  "enabled": true,
  "webhook_url": "https://your-webhook-url.com/notify",
  "message_template": {
    "event": "cookie_validation_failed",
    "cookie_name": "{cookie_name}",
    "status": "{status}",
    "reason": "{reason}",
    "timestamp": "{timestamp}",
    "custom_field": "custom_value"
  },
  "timeout": 15,
  "custom_headers": {
    "Authorization": "Bearer your-token",
    "X-Custom-Header": "custom-value"
  }
}
```

**响应**：
```json
{
  "success": true,
  "config": {
    "enabled": true,
    "webhook_url": "https://your-webhook-url.com/notify",
    "message_template": "{\"event\":\"cookie_validation_failed\",\"cookie_name\":\"{cookie_name}\",\"status\":\"{status}\",\"reason\":\"{reason}\",\"timestamp\":\"{timestamp}\",\"custom_field\":\"custom_value\"}",
    "timeout": 15,
    "custom_headers": "{\"Authorization\":\"Bearer your-token\",\"X-Custom-Header\":\"custom-value\"}",
    "updated_at": "2026-01-13 10:30:00"
  }
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "webhook_url_required",
  "message": "启用 webhook 时必须提供 webhook_url"
}
```

#### 3. 测试 Webhook 配置

**请求**：
```http
POST /weibo/api/webhook/test
Content-Type: application/json

{
  "cookie_name": "test_cookie",
  "status": "expired",
  "reason": "test_notification"
}
```

**响应**：
```json
{
  "success": true,
  "message": "Webhook 测试成功"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "http_error_404",
  "message": "Webhook 测试失败: http_error_404"
}
```

### Cookie 检测定时任务

#### 1. 获取 Cookie 检测定时配置

**请求**：
```http
GET /weibo/api/cookie_check/schedule/config
```

**响应**：
```json
{
  "success": true,
  "config": {
    "enabled": false,
    "cron_expression": "0 * * * *",
    "last_run_time": "",
    "next_run_time": ""
  }
}
```

#### 2. 更新 Cookie 检测定时配置

**请求**：
```http
PUT /weibo/api/cookie_check/schedule/config
Content-Type: application/json

{
  "enabled": true,
  "cron_expression": "0 */2 * * *"
}
```

**响应**：
```json
{
  "success": true,
  "config": {
    "enabled": true,
    "cron_expression": "0 */2 * * *",
    "last_run_time": "",
    "next_run_time": ""
  }
}
```

**错误响应**（无效的 cron 表达式）：
```json
{
  "success": false,
  "error": "invalid_cron",
  "message": "cron 表达式必须包含 5 个部分（分 时 日 月 周）"
}
```

#### 3. 手动触发 Cookie 检测

**请求**：
```http
POST /weibo/api/cookie_check/schedule/trigger
```

**响应**：
```json
{
  "success": true,
  "message": "Cookie 检测任务已触发"
}
```

#### 4. 验证所有 Cookie（带 Webhook 通知）

**请求**：
```http
POST /weibo/api/cookie_bundles/validate_all?send_webhook=true
```

**参数**：
- `send_webhook`（可选）：是否发送 Webhook 通知，默认为 true

**响应**：
```json
{
  "success": true,
  "results": [
    {
      "name": "cookie_bundle_1",
      "valid": true,
      "status": "ok"
    },
    {
      "name": "cookie_bundle_2",
      "valid": false,
      "status": "expired"
    }
  ]
}
```

## Webhook 通知格式

当 Cookie 验证失败时，系统会向配置的 Webhook URL 发送 POST 请求。

**默认请求格式**：

```http
POST https://your-webhook-url.com/notify
Content-Type: application/json

{
  "event": "cookie_validation_failed",
  "cookie_name": "cookie_bundle_1",
  "status": "expired",
  "reason": "cookie_expired",
  "timestamp": "2026-01-13 10:30:00"
}
```

**自定义请求格式示例**：

你可以通过配置 `message_template` 和 `custom_headers` 来自定义请求格式。

例如，钉钉机器人格式：

```json
{
  "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN",
  "message_template": {
    "msgtype": "text",
    "text": {
      "content": "⚠️ Cookie 失效通知\n\nCookie 名称: {cookie_name}\n状态: {status}\n原因: {reason}\n时间: {timestamp}"
    }
  }
}
```

企业微信机器人格式：

```json
{
  "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY",
  "message_template": {
    "msgtype": "markdown",
    "markdown": {
      "content": "## Cookie 失效通知\n\n> Cookie 名称: {cookie_name}\n> 状态: <font color=\"warning\">{status}</font>\n> 原因: {reason}\n> 时间: {timestamp}"
    }
  }
}
```

飞书机器人格式：

```json
{
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_HOOK",
  "message_template": {
    "msg_type": "text",
    "content": {
      "text": "⚠️ Cookie 失效通知\n\nCookie 名称: {cookie_name}\n状态: {status}\n原因: {reason}\n时间: {timestamp}"
    }
  }
}
```

## 使用示例

### 示例 1：配置钉钉机器人通知

```bash
# 1. 配置 Webhook
curl -X PUT http://localhost:8080/weibo/api/webhook/config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN",
    "message_template": {
      "msgtype": "text",
      "text": {
        "content": "⚠️ Cookie 失效通知\n\nCookie 名称: {cookie_name}\n状态: {status}\n原因: {reason}\n时间: {timestamp}"
      }
    },
    "timeout": 10
  }'

# 2. 测试 Webhook
curl -X POST http://localhost:8080/weibo/api/webhook/test \
  -H "Content-Type: application/json" \
  -d '{
    "cookie_name": "test_cookie",
    "status": "expired",
    "reason": "测试通知"
  }'

# 3. 启用定时检测（每小时检测一次）
curl -X PUT http://localhost:8080/weibo/api/cookie_check/schedule/config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "cron_expression": "0 * * * *"
  }'
```

### 示例 2：配置企业微信机器人通知

```bash
curl -X PUT http://localhost:8080/weibo/api/webhook/config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY",
    "message_template": {
      "msgtype": "markdown",
      "markdown": {
        "content": "## Cookie 失效通知\n\n> Cookie 名称: {cookie_name}\n> 状态: <font color=\"warning\">{status}</font>\n> 原因: {reason}\n> 时间: {timestamp}"
      }
    },
    "timeout": 10
  }'
```

### 示例 3：配置自定义 API 通知（带认证）

```bash
curl -X PUT http://localhost:8080/weibo/api/webhook/config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "webhook_url": "https://your-api.com/notifications",
    "message_template": {
      "type": "cookie_alert",
      "data": {
        "cookie_name": "{cookie_name}",
        "status": "{status}",
        "reason": "{reason}",
        "timestamp": "{timestamp}",
        "severity": "high"
      }
    },
    "timeout": 15,
    "custom_headers": {
      "Authorization": "Bearer your-api-token",
      "X-API-Key": "your-api-key"
    }
  }'
```

### 示例 4：手动触发检测

```bash
# 手动触发一次检测
curl -X POST http://localhost:8080/weibo/api/cookie_check/schedule/trigger
```

### 示例 5：Python 接收 Webhook 通知

```python
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route('/notify', methods=['POST'])
def webhook_handler():
    data = request.json

    if data.get('event') == 'cookie_validation_failed':
        cookie_name = data.get('cookie_name')
        status = data.get('status')
        reason = data.get('reason')
        timestamp = data.get('timestamp')

        # 处理通知
        print(f"[{timestamp}] Cookie 失效: {cookie_name} - {status} ({reason})")

        # 这里可以添加你的处理逻辑
        # 例如：发送邮件、短信、其他通知等
        send_email_notification(cookie_name, status, reason)

    return jsonify({"success": True})

def send_email_notification(cookie_name, status, reason):
    # 实现邮件通知逻辑
    pass

if __name__ == '__main__':
    app.run(port=5000)
```

## 常见问题

### Q1: 如何查看定时任务是否正常运行？

A: 可以通过以下方式检查：

1. 查看日志文件 `logs/web.log`，搜索 "Cookie 检测定时任务"
2. 调用 API 查看 `last_run_time` 字段
3. 查看 Cookie Bundle 的 `last_checked_at` 字段

### Q2: Webhook 通知失败怎么办？

A: Webhook 通知失败不会影响 Cookie 检测流程，失败信息会记录在日志中。建议：

1. 使用测试接口 `/weibo/api/webhook/test` 验证配置
2. 检查 Webhook URL 是否正确
3. 确保 Webhook 服务可访问
4. 查看日志文件了解具体错误信息
5. 检查自定义请求头和消息模板格式是否正确

### Q3: 如何临时禁用 Webhook 通知？

A: 调用更新配置 API，将 `enabled` 设置为 `false`：

```bash
curl -X PUT http://localhost:8080/weibo/api/webhook/config \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### Q4: 如何临时禁用定时检测？

A: 调用更新配置 API，将 `enabled` 设置为 `false`：

```bash
curl -X PUT http://localhost:8080/weibo/api/cookie_check/schedule/config \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### Q5: 定时任务会重复执行吗？

A: 不会。系统使用 Redis 分布式锁机制，确保同一时间只有一个检测任务在运行。

### Q6: 消息模板支持哪些变量？

A: 目前支持以下变量：

- `{cookie_name}`：Cookie Bundle 名称
- `{status}`：Cookie 状态（ok/expired/error）
- `{reason}`：失败原因
- `{timestamp}`：检测时间

变量会在发送前自动替换为实际值。

### Q7: 如何配置多个 Webhook 地址？

A: 目前系统只支持配置一个 Webhook 地址。如果需要通知多个地址，建议：

1. 搭建一个中转服务，接收通知后转发到多个目标
2. 或者在接收端实现转发逻辑

## 技术实现

### 核心组件

1. **APScheduler**：定时任务调度器
2. **Redis**：存储配置和分布式锁
3. **httpx**：发送 Webhook 通知
4. **FastAPI**：提供 RESTful API

### 关键函数

- `scheduled_cookie_check()`：定时任务执行函数
- `_validate_cookie_string()`：Cookie 验证函数
- `_send_webhook_with_config()`：使用配置发送 Webhook 通知
- `get_webhook_config()`：获取 Webhook 配置
- `save_webhook_config()`：保存 Webhook 配置
- `reload_cookie_check_schedule()`：重新加载定时任务配置

### 数据流程

```
定时触发 → 获取所有 Cookie Bundle → 逐个验证 → 更新状态 → 失败时发送 Webhook → 记录日志
```

### 配置存储结构

所有配置存储在 Redis Hash 结构中：

- `weibo:webhook:config`：Webhook 配置
- `weibo:cookie:schedule:config`：定时任务配置
- `weibo:cookie:schedule:lock`：定时任务分布式锁

## 注意事项

1. **Webhook URL 安全**：建议使用 HTTPS 并添加签名验证或 Token 认证
2. **检测频率**：不建议设置过高的检测频率，避免对微博服务器造成压力
3. **超时设置**：Webhook 请求超时时间可配置，范围 1-60 秒
4. **日志监控**：建议定期查看日志文件，确保功能正常运行
5. **Redis 依赖**：功能依赖 Redis，确保 Redis 服务正常运行
6. **消息模板格式**：消息模板必须是有效的 JSON 格式
7. **自定义请求头**：自定义请求头必须是有效的 JSON 格式
8. **配置持久化**：所有配置存储在 Redis 中，重启服务后配置仍然有效

## 更新日志

### v1.1.0 (2026-01-13)

- ✨ 新增 Webhook 配置管理 API
- ✨ 支持自定义 Webhook 消息模板
- ✨ 支持自定义 HTTP 请求头
- ✨ 新增 Webhook 测试接口
- 🔧 Webhook URL 和内容改为通过 API 配置
- 📝 完善文档和使用示例

### v1.0.0 (2026-01-13)

- ✨ 新增 Cookie 自动检测定时任务
- ✨ 新增 Webhook 通知功能
- ✨ 新增手动触发检测接口
- ✨ 新增定时任务配置管理接口
- 📝 完善文档和使用示例
