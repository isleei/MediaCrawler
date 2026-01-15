# Redis 到 MySQL 数据迁移文档

## 迁移概述

本文档记录了将微博 WebUI 配置数据从 Redis 迁移到 MySQL 的过程。

## 迁移时间

- 迁移日期：2026-01-13
- 迁移脚本：`migrate_data.py`
- 迁移服务：`api/services/weibo_storage.py`

## 迁移内容

### 1. 任务数据 (Tasks)
- **Redis Key**: `weibo:tasks`, `weibo:task:{id}`, `weibo:task:logs:{id}`
- **MySQL 表**: `web_ui_tasks`, `web_ui_task_logs`
- **迁移结果**: 51个任务（已存在，未重复迁移）
- **注意事项**: 任务日志中的 emoji 表情符号会被自动移除，避免 MySQL utf8mb4 编码问题

### 2. Cookie 数据
- **Redis Key**: `weibo:cookies`, `weibo:cookie:{name}`
- **MySQL 表**: `web_ui_cookies`
- **迁移结果**: 11个 cookie（已存在，未重复迁移）

### 3. Cookie Bundle 数据
- **Redis Key**: `weibo:cookie:bundle:{name}`
- **MySQL 表**: `web_ui_cookie_bundles`
- **迁移结果**: 3个 cookie bundle（已存在，未重复迁移）
- **包含字段**: cookie_string, proxies, user_agent, enabled, status

### 4. 代理数据 (Proxies)
- **Redis Key**: `weibo:proxies`
- **MySQL 表**: `web_ui_proxies`
- **迁移结果**: 0个代理

### 5. 情感词典 (Sentiment Words)
- **Redis Key**: `weibo:senti:{type}` (positive, negative, negation, degree, stopwords)
- **MySQL 表**: `web_ui_sentiment_words`
- **迁移结果**:
  - positive: 6506个词（0个新增）
  - negative: 11184个词（4573个新增）
  - negation: 15个词（15个新增）
  - degree: 220个词（220个新增）
  - stopwords: 2785个词（2777个新增）
  - **总计**: 20710个词，新增7585个

### 6. 配置数据 (Configs)
- **Redis Key**: `weibo:webhook:config`, `weibo:schedule:config`
- **MySQL 表**: `web_ui_configs`
- **迁移结果**: 2个配置
  - webhook 配置（企业微信通知）
  - schedule 配置（定时任务）

### 7. 批次数据 (Batches)
- **Redis Key**: `weibo:batches`, `weibo:batch:{id}`, `weibo:batch:logs:{id}`
- **MySQL 表**: `web_ui_batches`, `web_ui_task_logs`
- **迁移结果**: 3个批次

## 迁移特性

### 1. 去重处理
迁移脚本会自动检测已存在的数据，避免重复插入：
- 使用 `db.merge()` 或检查 `Duplicate entry` 错误
- 对于情感词典，使用批量查询检查是否已存在

### 2. 错误处理
- **Emoji 处理**: 自动移除日志中的 4 字节 UTF-8 字符（emoji），避免 MySQL 编码错误
- **批量提交**: 情感词典使用批量插入（每批500个），提高性能
- **错误恢复**: 单个记录失败不影响整体迁移

### 3. 性能优化
- 批量插入情感词典（batch_size=500）
- 使用数据库会话管理，减少连接开销
- 静默跳过重复数据，不打印冗余日志

## 使用方法

### 运行迁移脚本

```bash
# 确保环境变量已配置
# MONITOR_MYSQL_ENABLED=1
# MONITOR_MYSQL_HOST=your_host
# MONITOR_MYSQL_PORT=3306
# MONITOR_MYSQL_DBNAME=yuqing
# MONITOR_MYSQL_USER=root
# MONITOR_MYSQL_PASSWORD=your_password

# 运行迁移
uv run python migrate_data.py
```

### 环境变量配置

迁移脚本支持以下环境变量：

```bash
# MySQL 配置（优先级高）
MONITOR_MYSQL_ENABLED=1
MONITOR_MYSQL_HOST=192.168.2.13
MONITOR_MYSQL_PORT=3306
MONITOR_MYSQL_DBNAME=yuqing
MONITOR_MYSQL_USER=root
MONITOR_MYSQL_PASSWORD=your_password
MONITOR_MYSQL_CHARSET=utf8mb4

# 或使用通用配置（优先级低）
MYSQL_DB_HOST=192.168.2.13
MYSQL_DB_PORT=3306
MYSQL_DB_NAME=yuqing
MYSQL_DB_USER=root
MYSQL_DB_PWD=your_password
MYSQL_CHARSET=utf8mb4

# Redis 配置
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

## 数据库表结构

### web_ui_tasks
```sql
CREATE TABLE web_ui_tasks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    task_id VARCHAR(50) UNIQUE INDEX,
    keyword VARCHAR(255),
    max_pages INT,
    with_comments INT,
    status VARCHAR(50),
    created_at VARCHAR(50),
    started_at VARCHAR(50),
    finished_at VARCHAR(50),
    items_count INT DEFAULT 0,
    pages_crawled INT DEFAULT 0,
    content_inserted INT DEFAULT 0,
    content_updated INT DEFAULT 0,
    comment_inserted INT DEFAULT 0,
    comment_updated INT DEFAULT 0,
    pid VARCHAR(20),
    output_file VARCHAR(255),
    data_key VARCHAR(255),
    task_type VARCHAR(50) DEFAULT 'weibo'
);
```

### web_ui_cookies
```sql
CREATE TABLE web_ui_cookies (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) UNIQUE INDEX,
    value TEXT,  -- JSON string
    enabled INT DEFAULT 1,
    status VARCHAR(50) DEFAULT 'unknown',
    cookie_type VARCHAR(50) DEFAULT 'weibo'
);
```

### web_ui_cookie_bundles
```sql
CREATE TABLE web_ui_cookie_bundles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) UNIQUE INDEX,
    cookie_string TEXT,
    proxies TEXT,  -- JSON string
    user_agent TEXT,
    updated_at VARCHAR(50),
    enabled INT DEFAULT 1,
    status VARCHAR(50) DEFAULT 'unknown',
    bundle_type VARCHAR(50) DEFAULT 'weibo'
);
```

### web_ui_sentiment_words
```sql
CREATE TABLE web_ui_sentiment_words (
    id INT PRIMARY KEY AUTO_INCREMENT,
    word_type VARCHAR(50) INDEX,  -- positive, negative, negation, degree, stopwords
    word VARCHAR(100) INDEX,
    platform VARCHAR(50) DEFAULT 'weibo'
);
```

### web_ui_configs
```sql
CREATE TABLE web_ui_configs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    config_key VARCHAR(100) UNIQUE INDEX,  -- schedule, webhook
    config_value TEXT,  -- JSON string
    config_type VARCHAR(50) DEFAULT 'weibo'
);
```

## 迁移后验证

### 1. 检查数据完整性

```sql
-- 检查任务数量
SELECT COUNT(*) FROM web_ui_tasks WHERE task_type = 'weibo';

-- 检查 cookie bundle 数量
SELECT COUNT(*) FROM web_ui_cookie_bundles WHERE bundle_type = 'weibo';

-- 检查情感词数量
SELECT word_type, COUNT(*) FROM web_ui_sentiment_words
WHERE platform = 'weibo'
GROUP BY word_type;

-- 检查配置
SELECT config_key FROM web_ui_configs WHERE config_type = 'weibo';
```

### 2. 测试 WebUI 功能

启动 WebUI 服务并测试：
```bash
uv run uvicorn api.main:app --port 8080 --reload
```

访问 `http://localhost:8080` 验证：
- 任务列表是否正常显示
- Cookie 管理功能是否正常
- 配置是否正确加载

## 注意事项

1. **字符编码**: MySQL 表必须使用 `utf8mb4` 字符集，以支持 emoji 等特殊字符
2. **重复运行**: 迁移脚本支持重复运行，会自动跳过已存在的数据
3. **数据备份**: 迁移前建议备份 Redis 数据：`redis-cli --rdb /path/to/backup.rdb`
4. **性能考虑**: 情感词典数据量大（2万+），迁移可能需要几分钟
5. **日志清理**: 任务日志中的 emoji 会被自动移除，不影响功能

## 回滚方案

如果需要回滚到 Redis：

1. 停止使用 MySQL：设置 `MONITOR_MYSQL_ENABLED=0`
2. 确保 Redis 数据完整
3. 重启 WebUI 服务

## 相关文件

- `migrate_data.py` - 迁移脚本入口
- `api/services/weibo_storage.py` - 存储服务和迁移逻辑
- `database/models.py` - 数据库模型定义
- `database/db_utils.py` - 数据库连接工具

## 后续优化建议

1. **索引优化**: 为常用查询字段添加索引
2. **分区表**: 对于大量历史数据，考虑使用分区表
3. **定期清理**: 定期清理过期的任务日志和数据
4. **监控告警**: 添加数据库连接和性能监控
