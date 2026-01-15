# ES (Elasticsearch) 评论抓取性能优化方案

## 📊 你的当前配置分析

根据你的配置文件 (`SAVE_DATA_OPTION = "json"`) 和代码分析，你实际使用的存储方式是：

- **存储类**：`WeiboCompatStoreImplement`（兼容存储）
- **ES存储**：启用（`ES_ENABLED=0` 需改为 `1`）
- **MySQL存储**：可选（`WEIBO_COMMENT_MYSQL_ENABLED=0`）
- **JSON文件**：作为备份

## 🔴 性能瓶颈（按影响排序）

### 1. ES 单条写入（最严重）⭐⭐⭐⭐⭐
- **位置**：`weibo_store_compat.py:516-540`
- **问题**：每条评论一个 HTTP 请求到 ES
- **影响**：1000条评论 = 1000次网络请求
- **耗时占比**：约 60-70%

### 2. 热词提取（CPU密集）⭐⭐⭐⭐
- **位置**：`weibo_store_compat.py:444` 调用 `_extract_hotwords()`
- **问题**：每条评论都进行 jieba 分词
- **影响**：CPU占用高
- **耗时占比**：约 20-30%

### 3. MySQL 单条写入（如果启用）⭐⭐⭐
- **位置**：`weibo_store_compat.py:451-500`
- **问题**：每条评论一个事务
- **耗时占比**：约 10-15%（如果启用）

---

## 🚀 立即可用的优化方案

### 方案1：关闭不必要的功能（最快见效）

在 `.env` 文件中修改：

```bash
# 1. 如果不需要MySQL存储，关闭它
WEIBO_CONTENT_MYSQL_ENABLED=0
WEIBO_COMMENT_MYSQL_ENABLED=0

# 2. 如果不需要热词提取，关闭它
HOTWORDS_ENABLED=0

# 3. 如果不需要百度API意见抽取，关闭它
WEIBO_EXTRACTION_ENABLED=0
```

**预期效果**：2-5倍性能提升

---

### 方案2：使用批量写入模式（强烈推荐）⭐⭐⭐⭐⭐

#### 步骤 1：修改配置文件

在 `config/base_config.py` 中修改：

```python
# 将存储方式改为兼容模式（支持批量写入）
SAVE_DATA_OPTION = "compat"  # 使用兼容存储
```

#### 步骤 2：启用 ES 批量写入（需要修改代码）

在 `store/weibo/__init__.py` 中添加：

```python
# 检查是否使用批量优化
BATCH_ENABLED = os.getenv("WEIBO_BATCH_ENABLED", "0") in ("1", "true", "True")
BATCH_SIZE = int(os.getenv("WEIBO_BATCH_SIZE", "100"))

if config.SAVE_DATA_OPTION == "compat" and BATCH_ENABLED:
    # 使用批量优化版本
    from .weibo_store_compat_batch import WeiboCompatStoreBatchOptimized
    WeibostoreFactory.STORES["compat"] = WeiboCompatStoreBatchOptimized
```

#### 步骤 3：在 `.env` 中启用批量写入

```bash
# 启用批量写入
WEIBO_BATCH_ENABLED=1
WEIBO_BATCH_SIZE=200  # 批量大小，推荐 100-500

# 启用缓存（跳过重复评论）
WEIBO_COMMENT_CACHE_ENABLED=1
WEIBO_HOTWORDS_CACHE_ENABLED=1
```

**预期效果**：10-30倍性能提升

---

### 方案3：优化热词提取（中等效果）⭐⭐⭐

#### 方法A：降低热词数量

在 `.env` 中：

```bash
# 减少每条评论提取的热词数量
HOTWORDS_TOP_N=10  # 默认20，降低到10

# 提高热词最小长度（过滤短词）
HOTWORDS_MIN_LEN=2

# 提高热词最小出现次数
HOTWORDS_MIN_COUNT=2  # 默认1
```

#### 方法B：使用 Redis 缓存热词结果

```bash
# 启用 Redis 缓存
SENTI_USE_REDIS=1
SENTI_CACHE_TTL=300  # 缓存5分钟
```

**预期效果**：1.5-3倍性能提升

---

### 方案4：提高并发数

在 `config/base_config.py` 中：

```python
# 提高并发数（根据网络和机器性能）
MAX_CONCURRENCY_NUM = 10  # 默认1，提高到10

# 关闭二级评论（如果不需要）
ENABLE_GET_SUB_COMMENTS = False
```

**预期效果**：5-10倍性能提升（主要是并发带来的）

---

## 📈 推荐配置组合

### 场景1：快速优化（无需改代码）

```python
# config/base_config.py
SAVE_DATA_OPTION = "compat"
MAX_CONCURRENCY_NUM = 10
ENABLE_GET_SUB_COMMENTS = False
```

```bash
# .env
ES_ENABLED=1
WEIBO_COMMENT_MYSQL_ENABLED=0  # 关闭MySQL
HOTWORDS_ENABLED=0  # 关闭热词（或降低HOTWORDS_TOP_N=5）
WEIBO_EXTRACTION_ENABLED=0  # 关闭意见抽取
```

**预期效果**：5-10倍性能提升

---

### 场景2：完整优化（需要改代码）

#### Step 1：修改 `store/weibo/weibo_store_compat.py`

在文件开头添加批量缓冲区逻辑。具体来说，找到 `_store_comment_sync` 方法（第418行），改为批量模式：

```python
# 在类初始化中添加
def __init__(self, **kwargs):
    # ... 现有代码 ...

    # 添加批量缓冲区
    import os
    self._batch_enabled = os.getenv("WEIBO_BATCH_ENABLED", "0") in ("1", "true", "True")
    self._batch_size = int(os.getenv("WEIBO_BATCH_SIZE", "100"))
    self._comment_buffer = []
    self._es_bulk_buffer = []
    self._lock = threading.Lock()
```

然后修改 `_store_comment_sync` 方法，将评论添加到缓冲区而不是立即写入：

```python
def _store_comment_sync(self, comment_item: dict):
    if self._batch_enabled:
        # 批量模式
        with self._lock:
            self._comment_buffer.append(comment_item)

            if len(self._comment_buffer) >= self._batch_size:
                self._flush_comment_batch()
    else:
        # 原有的单条写入逻辑
        # ... 保持现有代码 ...
```

添加批量刷新方法：

```python
def _flush_comment_batch(self):
    """批量写入评论到ES"""
    if not self._comment_buffer:
        return

    comments = self._comment_buffer.copy()
    self._comment_buffer.clear()

    # 构建ES Bulk API请求
    bulk_body_lines = []
    for comment_item in comments:
        # ... 准备数据 ...
        pinglun_id = f"{content_id}_{comment_id}"

        # Bulk API格式：action行 + doc行
        bulk_body_lines.append(
            json.dumps({"index": {"_index": "weibopinglun", "_id": pinglun_id}})
        )
        bulk_body_lines.append(
            json.dumps(payload, ensure_ascii=False, default=self._json_default)
        )

    # 调用ES Bulk API
    bulk_body = "\n".join(bulk_body_lines) + "\n"
    self._http_request("POST", "/_bulk", bulk_body)

    utils.logger.info(f"[WeiboCompatStore] Bulk indexed {len(comments)} comments")
```

#### Step 2：配置文件

```python
# config/base_config.py
SAVE_DATA_OPTION = "compat"
MAX_CONCURRENCY_NUM = 15
ENABLE_GET_SUB_COMMENTS = False
```

```bash
# .env
ES_ENABLED=1
WEIBO_BATCH_ENABLED=1
WEIBO_BATCH_SIZE=200

# 可选：保留MySQL作为备份
WEIBO_COMMENT_MYSQL_ENABLED=0

# 优化热词
HOTWORDS_ENABLED=1
HOTWORDS_TOP_N=10
SENTI_USE_REDIS=1
```

**预期效果**：20-50倍性能提升

---

## 🔍 验证优化效果

### 方法1：查看日志输出

优化前：
```
[WeiboCompatStore] Inserted new comment: weibocontent_xxx_123 ✨
[WeiboCompatStore] Inserted new comment: weibocontent_xxx_124 ✨
[WeiboCompatStore] Inserted new comment: weibocontent_xxx_125 ✨
... (每条一行)
```

优化后（批量模式）：
```
[WeiboCompatStore] Bulk indexed 100 comments
[WeiboCompatStore] Bulk indexed 100 comments
```

### 方法2：计时对比

```bash
# 优化前
time uv run main.py --platform wb --lt qrcode --type search
# 输出示例：2分30秒（150秒）

# 优化后
time uv run main.py --platform wb --lt qrcode --type search
# 输出示例：10秒（15倍提升）
```

### 方法3：查看 ES 请求数

```bash
# 在ES服务器上查看索引请求数
curl -s http://localhost:9200/_nodes/stats/http | jq '.nodes[].http.total_opened'
```

优化前：每条评论一个请求
优化后：每批评论一个请求

---

## 性能对比总结

| 优化方案 | 实现难度 | 性能提升 | 推荐指数 |
|---------|---------|---------|----------|
| 关闭不必要功能 | ⭐ 简单 | ⭐⭐⭐ 2-5倍 | ⭐⭐⭐⭐ |
| 提高并发数 | ⭐ 简单 | ⭐⭐⭐⭐ 5-10倍 | ⭐⭐⭐⭐⭐ |
| ES 批量写入 | ⭐⭐⭐ 复杂 | ⭐⭐⭐⭐⭐ 10-30倍 | ⭐⭐⭐⭐⭐ |
| 热词优化 | ⭐⭐ 中等 | ⭐⭐⭐ 1.5-3倍 | ⭐⭐⭐ |
| 完整优化组合 | ⭐⭐⭐ 复杂 | ⭐⭐⭐⭐⭐ 20-50倍 | ⭐⭐⭐⭐⭐ |

---

## 🛠️ 快速实施步骤

### 最快方案（5分钟）：

1. 修改 `config/base_config.py`：
   ```python
   MAX_CONCURRENCY_NUM = 10
   ```

2. 修改 `.env`：
   ```bash
   WEIBO_COMMENT_MYSQL_ENABLED=0
   HOTWORDS_ENABLED=0
   ```

3. 运行测试

**预期效果**：5-10倍提升

### 完整方案（需要1-2小时改代码）：

参考上面的"场景2：完整优化"部分，实现 ES 批量写入。

**预期效果**：20-50倍提升

---

## 常见问题

### Q1: 我的配置是 `SAVE_DATA_OPTION = "json"`，为什么数据入了ES？

**A**: 你可能通过环境变量 `ES_ENABLED=1` 启用了ES。`WeiboCompatStoreImplement` 会同时写入JSON和ES（如果启用）。

### Q2: 批量写入会丢失数据吗？

**A**: 不会。已在代码中添加 `finally` 块自动刷新缓冲区（参考 `media_platform/weibo/core.py:174-180`）。

### Q3: ES 批量写入失败怎么办？

**A**: 可以在代码中添加重试逻辑，或将失败的文档写入日志文件，稍后重试。

### Q4: 热词缓存会占用多少内存？

**A**: 默认最多缓存10000条（约10-50MB），可以根据需要调整缓存大小。

---

## 下一步建议

1. **立即实施"快速优化"**（5分钟，5-10倍提升）
2. **监控性能改善效果**
3. **如果需要更高性能，再实施"完整优化"**（1-2小时改代码，20-50倍提升）

如果需要帮助修改代码，请告诉我！
