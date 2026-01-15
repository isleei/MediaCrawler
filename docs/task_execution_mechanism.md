# 爬虫任务执行机制分析

## 当前实现

### 执行方式：并发执行（无限制）

从代码分析来看，当前的爬虫任务执行机制如下：

```python
def start_task(task_id, keyword, max_pages):
    def _run():
        # 启动爬虫进程
        process = subprocess.Popen(cmd, ...)
        # 等待进程完成
        process.wait()

    # 每个任务在独立线程中运行
    threading.Thread(target=_run, daemon=True).start()
```

### 特点

1. **并发执行**
   - 每个任务启动时立即创建一个新线程
   - 每个线程启动一个独立的 Python 进程（`subprocess.Popen`）
   - 多个任务可以同时运行，没有数量限制

2. **独立进程**
   - 每个任务运行在独立的 Python 进程中
   - 进程间互不影响
   - 每个进程有独立的 PID

3. **异步启动**
   - 任务创建后立即返回
   - 不等待任务完成
   - 通过 daemon 线程在后台运行

### 配置参数

虽然 `config/base_config.py` 中定义了 `MAX_CONCURRENCY_NUM = 1`，但这个参数是用于**单个爬虫进程内部的并发控制**（同时爬取多少个帖子），而不是用于控制任务数量。

```python
# config/base_config.py
MAX_CONCURRENCY_NUM = 1  # 单个爬虫进程内部的并发数
```

### 潜在问题

1. **资源消耗**
   - 无限制并发可能导致系统资源耗尽
   - 每个任务启动一个完整的 Python 进程（包括浏览器）
   - 大量并发任务可能导致内存不足

2. **浏览器资源**
   - 每个任务启动一个 Playwright 浏览器实例
   - 浏览器是重量级资源，并发过多会导致性能下降

3. **平台限制**
   - 同时发起大量请求可能触发平台反爬虫机制
   - 可能导致 IP 被封禁或账号被限制

4. **数据库压力**
   - 多个任务同时写入数据库
   - 可能导致数据库连接池耗尽

## 建议改进

### 方案 1: 添加任务队列（推荐）

实现一个任务队列，限制同时运行的任务数量：

```python
import queue
import threading

# 全局任务队列
task_queue = queue.Queue()
MAX_CONCURRENT_TASKS = 3  # 最多同时运行3个任务
running_tasks = 0
queue_lock = threading.Lock()

def task_worker():
    """任务工作线程"""
    global running_tasks
    while True:
        task_id, keyword, max_pages = task_queue.get()
        try:
            with queue_lock:
                running_tasks += 1
            _run_task(task_id, keyword, max_pages)
        finally:
            with queue_lock:
                running_tasks -= 1
            task_queue.task_done()

# 启动工作线程
for _ in range(MAX_CONCURRENT_TASKS):
    threading.Thread(target=task_worker, daemon=True).start()

def start_task(task_id, keyword, max_pages):
    """将任务加入队列"""
    task_queue.put((task_id, keyword, max_pages))
    update_task(task_id, {"status": "queued"})
```

### 方案 2: 使用 Redis 分布式锁

利用现有的 Redis，实现分布式任务控制：

```python
def start_task(task_id, keyword, max_pages):
    # 检查当前运行的任务数
    running_count = len([k for k in weibo_storage.redis_client.keys(f"{TASK_SPIDER_LOCK_PREFIX}*")])

    if running_count >= MAX_CONCURRENT_TASKS:
        update_task(task_id, {"status": "queued"})
        return

    # 设置锁
    lock_key = f"{TASK_SPIDER_LOCK_PREFIX}{task_id}"
    weibo_storage.redis_client.setex(lock_key, 3600, "1")

    def _run():
        try:
            # 执行任务
            ...
        finally:
            # 释放锁
            weibo_storage.redis_client.delete(lock_key)

    threading.Thread(target=_run, daemon=True).start()
```

### 方案 3: 使用 Celery（生产环境推荐）

对于生产环境，建议使用 Celery 任务队列：

```python
from celery import Celery

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
def run_crawler_task(task_id, keyword, max_pages):
    """Celery 任务"""
    # 执行爬虫
    ...

def start_task(task_id, keyword, max_pages):
    """提交任务到 Celery"""
    run_crawler_task.delay(task_id, keyword, max_pages)
```

## 当前状态总结

| 特性 | 当前状态 | 建议 |
|------|---------|------|
| 并发控制 | ❌ 无限制 | ✅ 添加队列或限制 |
| 任务队列 | ❌ 无 | ✅ 实现队列机制 |
| 资源管理 | ❌ 无限制 | ✅ 限制并发数 |
| 任务优先级 | ❌ 无 | ⚠️ 可选 |
| 失败重试 | ❌ 无 | ⚠️ 可选 |
| 任务取消 | ✅ 支持（通过 PID） | ✅ 已实现 |

## 推荐配置

根据服务器资源，建议的并发任务数：

- **小型服务器**（2核4G）: 1-2 个任务
- **中型服务器**（4核8G）: 2-3 个任务
- **大型服务器**（8核16G+）: 3-5 个任务

## 实施建议

1. **短期**：添加环境变量 `MAX_CONCURRENT_TASKS`，实现简单的并发控制
2. **中期**：实现任务队列，支持任务排队和状态管理
3. **长期**：迁移到 Celery 或其他成熟的任务队列系统

## 相关文件

- `api/routers/weibo_ui.py:284` - `start_task()` 函数
- `config/base_config.py:94` - `MAX_CONCURRENCY_NUM` 配置（爬虫内部并发）
- `api/routers/weibo_ui.py:58` - `TASK_SPIDER_LOCK_PREFIX` 定义（未使用）
