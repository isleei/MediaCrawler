# Cookie 冗余和自动切换机制

## 功能概述

实现了 Cookie 冗余和自动切换机制，当检测到 Cookie 失效时，自动使用新的 Cookie 重试任务。

## 工作原理

### 1. Cookie 失效检测

任务执行失败时（返回码非 0），系统会：
1. 检测是否启用了 Cookie 重试（`ENABLE_COOKIE_RETRY`）
2. 检查重试次数是否超过限制（`MAX_COOKIE_RETRY`）
3. 如果满足条件，触发 Cookie 切换

### 2. Cookie 切换流程

```
任务失败 (return_code != 0)
    ↓
检查: 启用重试 && 未超过重试次数?
    ├─ 是 → 释放当前 Cookie
    │         ↓
    │      标记 Cookie 为 expired
    │         ↓
    │      分配新 Cookie (排除已尝试过的)
    │         ↓
    │      重新启动任务
    └─ 否 → 任务最终失败
```

### 3. Cookie 选择策略

分配新 Cookie 时：
1. 排除**正在使用**的 Cookie
2. 排除**已经尝试过**的 Cookie
3. 优先选择**状态为 ok** 的 Cookie
4. 如果没有健康的，选择第一个可用的

## 配置

### 环境变量

```bash
# 启用 Cookie 重试（默认启用）
ENABLE_COOKIE_RETRY=1

# 最大重试次数（默认 2 次）
MAX_COOKIE_RETRY=2
```

### 配置说明

- `ENABLE_COOKIE_RETRY=1`: 启用自动重试
- `ENABLE_COOKIE_RETRY=0`: 禁用自动重试，任务失败后不会切换 Cookie
- `MAX_COOKIE_RETRY=2`: 每个任务最多尝试 3 个 Cookie（初始 + 2 次重试）

## 使用场景

### 场景 1: Cookie 失效自动切换

假设有 3 个 Cookie: A, B, C

```
任务 1 使用 Cookie A 启动
    ↓
Cookie A 失效，任务失败
    ↓
自动切换到 Cookie B，重新启动
    ↓
Cookie B 正常，任务完成
```

### 场景 2: 多次重试

```
任务 1 使用 Cookie A → 失败
    ↓
重试 1: 使用 Cookie B → 失败
    ↓
重试 2: 使用 Cookie C → 成功
```

### 场景 3: 所有 Cookie 都失效

```
任务 1 使用 Cookie A → 失败
    ↓
重试 1: 使用 Cookie B → 失败
    ↓
重试 2: 使用 Cookie C → 失败
    ↓
达到最大重试次数，任务最终失败
```

## 日志示例

```
2026-01-13 18:00:00 INFO Starting task 1 with cookie bundle: cookie_a
2026-01-13 18:05:00 INFO 检测到 Cookie 可能失效 (返回码: 1)，准备使用新 Cookie 重试...
2026-01-13 18:05:01 INFO Retrying task 1 with new cookie: cookie_b (tried: ['cookie_a'])
2026-01-13 18:05:02 INFO Cookie 失效，使用新 Cookie 重试: cookie_b (第 1 次重试)
2026-01-13 18:10:00 INFO Task 1 completed successfully with cookie_b
```

## Cookie 状态管理

### 自动标记失效

当任务失败时，系统会自动：
1. 将失效的 Cookie Bundle 标记为 `expired`
2. 禁用该 Cookie Bundle（`enabled=false`）
3. 发送 Webhook 通知（如果配置了）

### 手动恢复

管理员可以：
1. 在 WebUI 中更新 Cookie
2. 重新验证 Cookie
3. 启用 Cookie Bundle

## 优势

### 1. 高可用性
- 单个 Cookie 失效不影响任务执行
- 自动切换，无需人工干预

### 2. 资源利用
- 充分利用所有可用的 Cookie
- 避免因单个 Cookie 失效导致任务堆积

### 3. 故障隔离
- 失效的 Cookie 自动禁用
- 不会影响其他任务

### 4. 可观测性
- 详细的重试日志
- Cookie 使用历史追踪
- 失败原因记录

## 监控指标

### 关键指标

1. **Cookie 重试率**
   - 重试次数 / 总任务数
   - 告警：> 30%

2. **Cookie 失效率**
   - 失效 Cookie 数 / 总 Cookie 数
   - 告警：> 50%

3. **任务最终成功率**
   - 成功任务数 / 总任务数（包括重试）
   - 告警：< 80%

4. **平均重试次数**
   - 总重试次数 / 重试任务数
   - 正常：< 1.5

## API 接口

### 查看任务重试历史

任务日志中会记录：
- 使用的 Cookie
- 重试次数
- 失败原因

```bash
GET /weibo/api/tasks/{task_id}/logs
```

### 查看 Cookie 使用情况

```bash
GET /weibo/api/tasks/queue/status
```

响应包含：
- `cookie_usage`: 当前 Cookie 使用情况
- `running_tasks`: 每个任务使用的 Cookie

## 最佳实践

### 1. Cookie 数量配置

建议配置：
- **最少**: 3 个 Cookie（支持 2 次重试）
- **推荐**: 5-6 个 Cookie（充足的冗余）
- **最多**: 根据账号数量决定

### 2. 重试次数配置

- **保守**: `MAX_COOKIE_RETRY=1`（最多尝试 2 个 Cookie）
- **推荐**: `MAX_COOKIE_RETRY=2`（最多尝试 3 个 Cookie）
- **激进**: `MAX_COOKIE_RETRY=3`（最多尝试 4 个 Cookie）

### 3. Cookie 维护

定期检查：
1. 每天验证所有 Cookie
2. 及时更新失效的 Cookie
3. 保持至少 3 个有效 Cookie

### 4. 告警设置

建议设置告警：
- Cookie 失效率 > 50%
- 可用 Cookie 数 < 2
- 任务重试率 > 30%

## 故障处理

### 问题 1: 所有 Cookie 都失效

**症状**: 任务全部失败，无法重试

**解决方案**:
1. 检查所有 Cookie Bundle 状态
2. 更新失效的 Cookie
3. 重新验证 Cookie
4. 重新启动失败的任务

### 问题 2: 频繁重试

**症状**: 大量任务需要重试

**可能原因**:
1. Cookie 质量差
2. 平台反爬虫升级
3. IP 被限制

**解决方案**:
1. 更新 Cookie
2. 配置代理 IP
3. 降低并发数

### 问题 3: 重试后仍然失败

**症状**: 尝试所有 Cookie 后仍失败

**可能原因**:
1. 所有 Cookie 都失效
2. 关键词被限制
3. 平台维护

**解决方案**:
1. 检查平台状态
2. 更新所有 Cookie
3. 更换关键词

## 测试

### 测试场景

1. **正常重试**
   - 禁用一个 Cookie
   - 创建任务使用该 Cookie
   - 验证自动切换到其他 Cookie

2. **达到重试限制**
   - 只保留 1 个 Cookie
   - 禁用该 Cookie
   - 验证任务最终失败

3. **并发重试**
   - 创建多个任务
   - 部分 Cookie 失效
   - 验证正确分配和重试

## 相关文件

- `api/routers/weibo_ui.py` - Cookie 重试实现
- `docs/task_queue_and_cookie_allocation.md` - 任务队列文档
- `docs/task_queue_defects_and_fixes.md` - 缺陷修复文档

## 总结

Cookie 冗余机制显著提高了系统的可用性和稳定性：
- ✅ 自动检测 Cookie 失效
- ✅ 自动切换到新 Cookie
- ✅ 支持多次重试
- ✅ 详细的日志记录
- ✅ 失效 Cookie 自动禁用

配合任务队列机制，系统可以实现：
- 高可用性（单点故障不影响整体）
- 高效率（充分利用所有资源）
- 易维护（自动化程度高）
