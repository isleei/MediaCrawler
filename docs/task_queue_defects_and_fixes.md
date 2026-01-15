# 任务队列实现缺陷检查和修复

## 已发现并修复的缺陷

### ✅ 缺陷 1: 进程异常退出时 Cookie 未释放

**问题描述**:
- `_refresh_task_status()` 函数检测到进程已死亡时，会将任务标记为 `stopped`
- 但没有调用 `release_cookie_for_task()`，导致 Cookie 永久被占用
- 队列中的任务无法启动

**影响**:
- 严重：Cookie 泄漏，最终导致所有 Cookie 被占用
- 队列中的任务永远无法启动

**修复**:
```python
def _refresh_task_status(task):
    if not _is_process_alive(pid):
        # ... 更新状态 ...

        # 释放 cookie 并处理队列
        release_cookie_for_task(task_id)
        process_queued_tasks()
```

**修复位置**: `api/routers/weibo_ui.py:157`

---

## 潜在缺陷检查

### ⚠️ 缺陷 2: 服务器重启后 Cookie 分配状态丢失

**问题描述**:
- `running_task_cookies` 是内存中的字典
- 服务器重启后，正在运行的任务信息丢失
- 可能导致多个任务使用同一个 Cookie

**影响**:
- 中等：服务器重启后需要手动清理

**建议修复**:
1. 启动时从数据库恢复运行中的任务
2. 重新分配 Cookie 或清理状态

**修复方案**:
```python
def init_task_queue():
    """初始化任务队列，恢复运行中的任务状态"""
    tasks = weibo_storage.list_tasks()
    for task in tasks:
        if task.get("status") == "running":
            task_id = task.get("id")
            cookie_name = task.get("data_key")  # 从任务中读取使用的 cookie

            # 检查进程是否还在运行
            if _is_process_alive(task.get("pid")):
                # 恢复 cookie 分配
                with task_queue_lock:
                    running_task_cookies[task_id] = cookie_name
                app_logger.info(f"Recovered task {task_id} with cookie {cookie_name}")
            else:
                # 进程已死，清理状态
                update_task(task_id, {"status": "stopped", "pid": ""})
                app_logger.info(f"Cleaned up dead task {task_id}")
```

**状态**: 待实现

---

### ⚠️ 缺陷 3: 并发竞争条件

**问题描述**:
- `get_available_cookie_bundle()` 和 `allocate_cookie_for_task()` 之间有时间窗口
- 理论上可能导致两个任务分配到同一个 Cookie

**影响**:
- 低：已使用 `task_queue_lock` 保护，但 `get_available_cookie_bundle()` 在锁外调用

**当前代码**:
```python
def allocate_cookie_for_task(task_id):
    with task_queue_lock:
        cookie_bundle = get_available_cookie_bundle()  # 在锁内调用，安全
        if cookie_bundle:
            running_task_cookies[task_id] = cookie_bundle
        return cookie_bundle
```

**状态**: ✅ 已安全（`get_available_cookie_bundle()` 在锁内调用）

---

### ⚠️ 缺陷 4: 队列中的任务无法取消

**问题描述**:
- 队列中的任务（status=queued）没有 PID
- 删除任务时不会触发队列处理

**影响**:
- 低：用户体验问题

**建议修复**:
在删除任务时检查是否为队列任务：
```python
@router.delete("/tasks/{task_id}")
async def delete_task_route(task_id: int):
    task = get_task(task_id)
    if task and task.get("status") == "queued":
        # 从队列中移除
        pass
    weibo_storage.delete_task(task_id)
    return {"success": True}
```

**状态**: 待实现（低优先级）

---

### ⚠️ 缺陷 5: Cookie Bundle 被禁用时未释放

**问题描述**:
- 如果正在使用的 Cookie Bundle 被禁用
- 任务仍在运行，但 Cookie 状态不一致

**影响**:
- 低：边缘情况

**建议**:
- 文档说明：不要禁用正在使用的 Cookie Bundle
- 或添加检查：禁用时警告用户

**状态**: 文档说明即可

---

### ⚠️ 缺陷 6: 没有任务超时机制

**问题描述**:
- 任务可能永久运行
- 占用 Cookie 和并发槽位

**影响**:
- 中等：可能导致资源耗尽

**建议修复**:
添加任务超时配置：
```python
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "3600"))  # 1小时

# 在任务启动时记录开始时间
# 定期检查超时任务并终止
```

**状态**: 待实现（中优先级）

---

### ⚠️ 缺陷 7: 队列顺序不可控

**问题描述**:
- 队列按创建时间顺序处理
- 无法设置优先级

**影响**:
- 低：功能增强

**状态**: 功能增强，非缺陷

---

### ⚠️ 缺陷 8: 没有 Cookie 健康检查

**问题描述**:
- 分配的 Cookie 可能已过期
- 任务启动后才发现 Cookie 失效

**影响**:
- 中等：任务失败率高

**建议修复**:
分配前验证 Cookie：
```python
def get_available_cookie_bundle():
    bundles = list_cookie_bundles()
    enabled_bundles = [b for b in bundles if b.get("enabled") == "1"]

    # 过滤出状态为 ok 的 bundle
    healthy_bundles = [b for b in enabled_bundles if b.get("status") == "ok"]

    used_bundles = set(running_task_cookies.values())
    available_bundles = [b for b in healthy_bundles if b.get("name") not in used_bundles]

    return available_bundles[0].get("name") if available_bundles else None
```

**状态**: 待实现（中优先级）

---

## 修复优先级

### 🔴 高优先级（已修复）
1. ✅ 进程异常退出时 Cookie 未释放

### 🟡 中优先级（建议修复）
2. ⚠️ 服务器重启后状态恢复
3. ⚠️ 任务超时机制
4. ⚠️ Cookie 健康检查

### 🟢 低优先级（可选）
5. ⚠️ 队列任务取消优化
6. ⚠️ Cookie Bundle 禁用检查
7. ⚠️ 队列优先级

---

## 测试建议

### 测试场景

1. **正常流程测试**
   - 创建 3 个任务，验证都能启动
   - 创建第 4 个任务，验证进入队列
   - 等待任务完成，验证队列任务自动启动

2. **异常流程测试**
   - 手动 kill 任务进程，验证 Cookie 释放
   - 停止任务，验证队列任务启动
   - 删除队列中的任务

3. **边界条件测试**
   - 没有 Cookie Bundle 时创建任务
   - 所有 Cookie Bundle 被禁用
   - Cookie Bundle 数量 < 并发限制

4. **并发测试**
   - 同时创建 10 个任务
   - 验证只有 3 个运行，7 个排队
   - 验证 Cookie 不重复

5. **服务器重启测试**
   - 启动任务后重启服务器
   - 验证状态恢复或清理

---

## 监控建议

### 关键指标

1. **Cookie 使用率**
   - 当前使用 / 总可用
   - 告警：> 80%

2. **队列长度**
   - 队列中的任务数
   - 告警：> 10

3. **任务成功率**
   - 完成 / (完成 + 失败)
   - 告警：< 80%

4. **平均任务时长**
   - 用于设置超时阈值

---

## 相关文件

- `api/routers/weibo_ui.py` - 主要实现
- `test_task_queue.py` - 测试脚本
- `docs/task_queue_and_cookie_allocation.md` - 使用文档
