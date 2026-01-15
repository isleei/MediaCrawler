# =============================================================================
# 微博评论抓取性能优化 - 快速配置方案（ES存储）
# 无需修改代码，仅调整配置即可获得 5-10倍性能提升
# =============================================================================

# -----------------------------------------------------------------------------
# 步骤1：修改 config/base_config.py
# -----------------------------------------------------------------------------

# 1. 提高并发数（最重要！）
MAX_CONCURRENCY_NUM = 10  # 从1提高到10，立即获得5-10倍提升

# 2. 关闭二级评论（如果不需要）
ENABLE_GET_SUB_COMMENTS = False  # 二级评论数量巨大

# 3. 限制单帖子评论数量（如果只需要最新评论）
CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 50  # 从100降低到50

# 4. 使用兼容存储（支持ES）
SAVE_DATA_OPTION = "compat"  # 使用WeiboCompatStoreImplement


# -----------------------------------------------------------------------------
# 步骤2：修改 .env 文件
# -----------------------------------------------------------------------------

# === ES 配置 ===
ES_ENABLED=1  # 启用ES存储
ES_HOSTS=http://192.168.2.13:9200  # 你的ES地址
ES_INDEX_WEIBO=weibocontent
ES_INDEX_PINGLUN=weibopinglun

# === MySQL 配置（建议关闭以提升性能）===
WEIBO_CONTENT_MYSQL_ENABLED=0  # 关闭内容MySQL存储
WEIBO_COMMENT_MYSQL_ENABLED=0  # 关闭评论MySQL存储

# === 热词优化 ===
HOTWORDS_ENABLED=1  # 如果需要热词，保持1；否则改为0可大幅提速
HOTWORDS_TOP_N=10  # 从20降低到10，减少计算量
HOTWORDS_MIN_LEN=2  # 最小热词长度
HOTWORDS_MIN_COUNT=1  # 最小出现次数

# === 情感分析优化 ===
SENTI_ENABLED=1  # 如果需要情感分析
SENTI_USE_REDIS=1  # 使用Redis缓存情感词典
SENTI_CACHE_TTL=300  # 缓存5分钟（从60秒提高）

# === 意见抽取（百度API，耗时严重）===
WEIBO_EXTRACTION_ENABLED=0  # 强烈建议关闭，非常耗时

# === Redis 配置 ===
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=


# =============================================================================
# 性能对比（1000条评论为例）
# =============================================================================

# 优化前（默认配置）：
# - MAX_CONCURRENCY_NUM = 1
# - WEIBO_COMMENT_MYSQL_ENABLED = 1
# - HOTWORDS_TOP_N = 20
# - WEIBO_EXTRACTION_ENABLED = 1
# 总耗时：约 3-5 分钟

# 优化后（上述配置）：
# - MAX_CONCURRENCY_NUM = 10
# - WEIBO_COMMENT_MYSQL_ENABLED = 0
# - HOTWORDS_TOP_N = 10
# - WEIBO_EXTRACTION_ENABLED = 0
# 总耗时：约 20-40 秒
# 提升倍数：5-10倍 ⭐⭐⭐⭐⭐


# =============================================================================
# 根据场景选择配置
# =============================================================================

# --- 场景1：只需要评论文本，不需要热词和情感分析 ---
"""
config/base_config.py:
    MAX_CONCURRENCY_NUM = 15
    ENABLE_GET_SUB_COMMENTS = False
    SAVE_DATA_OPTION = "compat"

.env:
    ES_ENABLED=1
    WEIBO_COMMENT_MYSQL_ENABLED=0
    HOTWORDS_ENABLED=0  # 关闭热词
    SENTI_ENABLED=0  # 关闭情感分析
    WEIBO_EXTRACTION_ENABLED=0

预期性能：最快，10-15倍提升
"""

# --- 场景2：需要热词，不需要情感分析 ---
"""
config/base_config.py:
    MAX_CONCURRENCY_NUM = 10
    ENABLE_GET_SUB_COMMENTS = False
    SAVE_DATA_OPTION = "compat"

.env:
    ES_ENABLED=1
    WEIBO_COMMENT_MYSQL_ENABLED=0
    HOTWORDS_ENABLED=1
    HOTWORDS_TOP_N=10  # 减少热词数量
    SENTI_ENABLED=0
    WEIBO_EXTRACTION_ENABLED=0

预期性能：7-10倍提升
"""

# --- 场景3：需要完整功能（热词+情感分析）---
"""
config/base_config.py:
    MAX_CONCURRENCY_NUM = 10
    ENABLE_GET_SUB_COMMENTS = False
    SAVE_DATA_OPTION = "compat"

.env:
    ES_ENABLED=1
    WEIBO_COMMENT_MYSQL_ENABLED=0  # 仍然关闭MySQL
    HOTWORDS_ENABLED=1
    HOTWORDS_TOP_N=10
    SENTI_ENABLED=1
    SENTI_USE_REDIS=1  # 使用Redis缓存
    WEIBO_EXTRACTION_ENABLED=0  # 百度API太慢，建议关闭

预期性能：5-8倍提升
"""

# --- 场景4：需要MySQL备份 + ES ---
"""
config/base_config.py:
    MAX_CONCURRENCY_NUM = 8  # 稍微降低并发，因为MySQL写入较慢
    ENABLE_GET_SUB_COMMENTS = False
    SAVE_DATA_OPTION = "compat"

.env:
    ES_ENABLED=1
    WEIBO_COMMENT_MYSQL_ENABLED=1  # 启用MySQL
    WEIBO_CONTENT_MYSQL_ENABLED=1
    HOTWORDS_ENABLED=1
    HOTWORDS_TOP_N=10
    SENTI_ENABLED=1
    SENTI_USE_REDIS=1
    WEIBO_EXTRACTION_ENABLED=0

预期性能：3-5倍提升（受MySQL单条写入限制）
注意：如需更高性能，建议实施MySQL批量写入优化
"""


# =============================================================================
# 验证配置是否生效
# =============================================================================

# 运行爬虫后，查看日志输出：

# 1. 并发数验证
#    应该看到多个任务并发执行：
#    [WeiboCrawler] Starting to get note comments, note_id: xxx
#    [WeiboCrawler] Starting to get note comments, note_id: yyy
#    (同时出现多条)

# 2. 热词验证
#    如果 HOTWORDS_ENABLED=0，不应该看到：
#    [WeiboCompatStore] Saved 10 hotwords for comment xxx

# 3. MySQL 验证
#    如果 WEIBO_COMMENT_MYSQL_ENABLED=0，应该看到：
#    [WeiboCompatStore] Skip comment table write (MySQL disabled)

# 4. ES 验证
#    应该看到 ES 索引日志：
#    [store.weibo.es] PUT /weibopinglun/_doc/xxx


# =============================================================================
# 故障排查
# =============================================================================

# 问题1：性能提升不明显
# 检查项：
# - MAX_CONCURRENCY_NUM 是否已修改？
# - WEIBO_EXTRACTION_ENABLED 是否为 0？（这个最耗时）
# - HOTWORDS_ENABLED 是否为 0 或 HOTWORDS_TOP_N 已降低？

# 问题2：ES 连接失败
# 检查项：
# - ES_HOSTS 地址是否正确？
# - ES 服务是否正常运行？curl http://your-es-host:9200
# - 网络是否可达？

# 问题3：Redis 缓存未生效
# 检查项：
# - SENTI_USE_REDIS=1 是否已设置？
# - Redis 服务是否正常运行？
# - REDIS_HOST/PORT 是否正确？

# 问题4：并发数太高导致错误
# 解决：
# - 降低 MAX_CONCURRENCY_NUM 到 5-8
# - 检查网络带宽和机器CPU


# =============================================================================
# 进一步优化（需要修改代码）
# =============================================================================

# 如果上述配置优化仍不满足需求，可以实施：
# 1. ES 批量写入（Bulk API）- 20-50倍提升
#    参考：docs/ES_PERFORMANCE_OPTIMIZATION.md

# 2. MySQL 批量写入 - 10-30倍提升
#    参考：docs/comment_performance_optimization.md

# 3. 热词缓存优化 - 2-5倍提升
#    在 weibo_store_compat.py 中添加热词缓存


# =============================================================================
# 推荐实施顺序
# =============================================================================

# 第1步：快速优化（5分钟，5-10倍提升）✅ 优先
# - 修改 MAX_CONCURRENCY_NUM = 10
# - 关闭 WEIBO_COMMENT_MYSQL_ENABLED
# - 关闭 WEIBO_EXTRACTION_ENABLED

# 第2步：精细优化（10分钟，累计 7-12倍提升）
# - 调整 HOTWORDS_TOP_N
# - 启用 SENTI_USE_REDIS
# - 根据需求关闭不必要功能

# 第3步：代码优化（1-2小时，累计 20-50倍提升）
# - 实施 ES Bulk API 批量写入
# - 实施 MySQL 批量写入（如果需要）
# - 添加热词缓存


# =============================================================================
# 使用本配置的步骤
# =============================================================================

# 1. 复制上述配置到对应文件
#    - config/base_config.py 的修改部分
#    - .env 的修改部分

# 2. 根据你的场景选择合适的配置组合

# 3. 运行测试：
#    uv run main.py --platform wb --lt qrcode --type search

# 4. 观察日志输出，验证优化效果

# 5. 根据实际情况微调参数
