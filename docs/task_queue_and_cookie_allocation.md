# 任务队列和 Cookie 分配机制

## 功能概述

实现了任务队列和 Cookie 自动分配机制，确保：
1. **并发控制**: 最多同时运行 3 个任务
2. **Cookie 隔离**: 每个任务使用独立的 Cookie Bundle
3. **自动队列**: 超过限制的任务自动进入队列
4. **自动调度**: 任务完成后自动启动队列中的下一个任务

## 配置

### 环境变量

```bash
# 最大并发任务数（默认 3）
MAX_CONCURRENT_TASKS=3
```

## 工作原理

### 1. 任务创建流程

```
用户创建任务
    ↓
检查并发限制
    ↓
是否 < 3 个任务？
    ├─ 是 → 分配可用 Cookie → 立即启动
    └─ 否 → 加入队列 → 等待
```

### 2. Cookie 分配策略

- 从所有**启用的** Cookie Bundle 中选择
- 排除**正在使用**的 Cookie Bundle
- 按顺序分配第一个可用的 Cookie
- 任务完成后自动释放 Cookie

### 3. 队列处理

任务完成或停止时：
1. 释放占用的 Cookie
2. 检查队列中的任务
3. 如果有可用 Cookie，启动下一个任务
4. 重复直到达到并发限制或队列为空

## 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 刚创建，准备启动 |
| `queued` | 在队列中等待 |
| `running` | 正在运行 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `stopped` | 已停止 |

## API 接口

### 查看队列状态

```bash
GET /weibo/api/tasks/queue/status
```

**响应示例**:
```json
{
  "max_concurrent": 3,
  "running_count": 2,
  "queued_count": 1,
  "running_tasks": [
    {
      "id": 1,
      "keyword": "Python",
      "cookie": "cookie_bundle_1"
    },
    {
      "id": 2,
      "keyword": "AI",
      "cookie": "cookie_bundle_2"
    }
  ],
  "queued_tasks": [
    {
      "id": 3,
      "keyword": "机器学习"
    }
  ],
  "cookie_usage": {
    "1": "cookie_bundle_1",
    "2": "cookie_bundle_2"
  }
}
```

### 创建任务

```bash
POST /weibo/api/tasks
Content-Type: application/json

{
  "keyword": "Python",
  "max_pages": 5,
  "with_comments": true
}
```

**响应**:
- 如果可以立即启动: `status: "running"`
- 如果需要排队: `status: "queued"`

### 停止任务

```bash
DELETE /weibo/api/tasks/{task_id}
```

停止任务会：
1. 终止爬虫进程
2. 释放占用的 Cookie
3. 自动启动队列中的下一个任务

## 使用示例

### 场景 1: 正常情况

假设有 3 个 Cookie Bundle: A, B, C

```
创建任务 1 → 分配 Cookie A → 立即启动
创建任务 2 → 分配 Cookie B → 立即启动
创建任务 3 → 分配 Cookie C → 立即启动
创建任务 4 → 无可用 Cookie → 加入队列
```

当任务 1 完成：
```
任务 1 完成 → 释放 Cookie A → 任务 4 使用 Cookie A → 启动
```

### 场景 2: Cookie 不足

假设只有 2 个 Cookie Bundle: A, B

```
创建任务 1 → 分配 Cookie A → 立即启动
创建任务 2 → 分配 Cookie B → 立即启动
创建任务 3 → 无可用 Cookie → 加入队列（即使未达到并发限制）
```

### 场景 3: 手动停止任务

```
停止任务 1 → 释放 Cookie A → 队列中的任务 4 使用 Cookie A → 启动
```

## 日志示例

```
2026-01-13 17:00:00 INFO Starting task 1 with cookie bundle: cookie_bundle_1
2026-01-13 17:00:05 INFO Starting task 2 with cookie bundle: cookie_bundle_2
2026-01-13 17:00:10 INFO Starting task 3 with cookie bundle: cookie_bundle_3
2026-01-13 17:00:15 INFO Max concurrent tasks reached, queuing task 4
2026-01-13 17:05:00 INFO Task 1 finished, released cookie: cookie_bundle_1
2026-01-13 17:05:01 INFO Starting queued task 4 with cookie bundle: cookie_bundle_1
```

## 监控和调试

### 查看运行中的任务

```bash
curl http://localhost:8080/weibo/api/tasks/queue/status | jq
```

### 查看任务日志

```bash
curl http://localhost:8080/weibo/api/tasks/{task_id}/logs | jq
```

### 查看 Cookie Bundle 状态

```bash
curl http://localhost:8080/weibo/api/cookie_bundles | jq
```

## 注意事项

1. **Cookie Bundle 数量**
   - 至少需要 1 个启用的 Cookie Bundle
   - 建议配置 3 个或更多 Cookie Bundle
   - Cookie Bundle 数量决定了实际并发数

2. **任务队列**
   - 队列中的任务按创建时间顺序执行
   - 队列没有大小限制
   - 队列中的任务可以随时删除

3. **Cookie 状态**
   - 只有 `enabled=true` 的 Cookie Bundle 会被使用
   - 如果所有 Cookie 都被占用，新任务会进入队列
   - 可以动态添加/删除 Cookie Bundle

4. **并发限制**
   - 实际并发数 = min(MAX_CONCURRENT_TASKS, 可用 Cookie 数量)
   - 例如: 设置 MAX_CONCURRENT_TASKS=5，但只有 3 个 Cookie，实际只能运行 3 个任务

## 故障处理

### 任务卡住不释放 Cookie

如果任务进程异常退出，Cookie 可能不会自动释放。解决方法：

1. 重启 API 服务器（会清空内存中的 Cookie 分配记录）
2. 或手动停止任务

### 队列中的任务不启动

可能原因：
1. 没有可用的 Cookie Bundle
2. 所有 Cookie Bundle 都被禁用
3. 检查日志查看详细错误

### Cookie Bundle 被多个任务使用

这不应该发生。如果发生：
1. 检查是否有多个 API 服务器实例
2. 重启 API 服务器

## 测试

运行测试脚本：

```bash
uv run python test_task_queue.py
```

测试内容：
- 创建 5 个任务
- 验证只有 3 个任务运行
- 验证 2 个任务进入队列
- 验证每个任务使用不同的 Cookie

## 相关文件

- `api/routers/weibo_ui.py` - 任务队列实现
- `test_task_queue.py` - 测试脚本
- `docs/task_execution_mechanism.md` - 执行机制文档
