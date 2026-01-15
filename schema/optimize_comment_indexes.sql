-- =============================================================================
-- 微博评论表索引优化脚本
-- 用于提升评论抓取和查询性能
-- =============================================================================

USE media_crawler;  -- 根据实际数据库名修改

-- -----------------------------------------------------------------------------
-- 1. 检查现有索引
-- -----------------------------------------------------------------------------
-- 执行以下命令查看当前索引情况
-- SHOW INDEX FROM weibo_note_comment;
-- SHOW INDEX FROM weibo_note;


-- -----------------------------------------------------------------------------
-- 2. 微博评论表 (weibo_note_comment) 索引优化
-- -----------------------------------------------------------------------------

-- 2.1 主键索引（如果不存在）
-- comment_id 应该是主键，如果不是则添加
-- ALTER TABLE weibo_note_comment ADD PRIMARY KEY (comment_id);

-- 2.2 帖子ID索引（重要：用于批量查询某帖子的所有评论）
-- 检查是否存在
SELECT DISTINCT INDEX_NAME
FROM INFORMATION_SCHEMA.STATISTICS
WHERE TABLE_SCHEMA = 'media_crawler'
  AND TABLE_NAME = 'weibo_note_comment'
  AND COLUMN_NAME = 'note_id';

-- 如果不存在，添加索引
CREATE INDEX IF NOT EXISTS idx_note_id
ON weibo_note_comment(note_id);

-- 2.3 复合索引（用于分页查询最新评论）
-- 场景：SELECT * FROM weibo_note_comment WHERE note_id = ? ORDER BY create_time DESC LIMIT 100;
CREATE INDEX IF NOT EXISTS idx_note_createtime
ON weibo_note_comment(note_id, create_time DESC);

-- 2.4 用户评论索引（用于查询某用户的所有评论）
CREATE INDEX IF NOT EXISTS idx_user_id
ON weibo_note_comment(user_id);

-- 2.5 父评论索引（用于查询二级评论）
-- 场景：SELECT * FROM weibo_note_comment WHERE parent_comment_id = ?;
CREATE INDEX IF NOT EXISTS idx_parent_comment
ON weibo_note_comment(parent_comment_id);

-- 2.6 时间范围查询索引
-- 场景：查询某时间段的评论
CREATE INDEX IF NOT EXISTS idx_create_time
ON weibo_note_comment(create_time DESC);


-- -----------------------------------------------------------------------------
-- 3. 微博内容表 (weibo_note) 索引优化
-- -----------------------------------------------------------------------------

-- 3.1 主键索引
-- note_id 应该是主键
-- ALTER TABLE weibo_note ADD PRIMARY KEY (note_id);

-- 3.2 用户ID索引（用于查询某用户的所有帖子）
CREATE INDEX IF NOT EXISTS idx_user_id
ON weibo_note(user_id);

-- 3.3 发布时间索引（用于按时间排序）
CREATE INDEX IF NOT EXISTS idx_publish_time
ON weibo_note(publish_time DESC);

-- 3.4 复合索引（用于查询某用户的最新帖子）
CREATE INDEX IF NOT EXISTS idx_user_publish
ON weibo_note(user_id, publish_time DESC);


-- -----------------------------------------------------------------------------
-- 4. 验证索引效果
-- -----------------------------------------------------------------------------

-- 4.1 查看评论表索引
SHOW INDEX FROM weibo_note_comment;

-- 4.2 查看内容表索引
SHOW INDEX FROM weibo_note;

-- 4.3 测试查询性能（执行计划）
-- 应该显示 type='ref' 或 'range'，key 显示使用了相应索引

-- 测试1：按 comment_id 查询（主键）
EXPLAIN SELECT * FROM weibo_note_comment WHERE comment_id = 'test_id';
-- 预期：type=const, key=PRIMARY

-- 测试2：按 note_id 查询（批量查询评论）
EXPLAIN SELECT * FROM weibo_note_comment WHERE note_id = 'test_note_id';
-- 预期：type=ref, key=idx_note_id

-- 测试3：按 note_id 分页查询
EXPLAIN SELECT * FROM weibo_note_comment
WHERE note_id = 'test_note_id'
ORDER BY create_time DESC
LIMIT 100;
-- 预期：type=ref, key=idx_note_createtime

-- 测试4：按 user_id 查询
EXPLAIN SELECT * FROM weibo_note_comment WHERE user_id = 'test_user_id';
-- 预期：type=ref, key=idx_user_id


-- -----------------------------------------------------------------------------
-- 5. 索引维护建议
-- -----------------------------------------------------------------------------

-- 5.1 定期分析表（更新索引统计信息）
-- 建议每周执行一次
ANALYZE TABLE weibo_note_comment;
ANALYZE TABLE weibo_note;

-- 5.2 优化表（重建索引，回收空间）
-- 建议每月执行一次，在业务低峰期
-- OPTIMIZE TABLE weibo_note_comment;
-- OPTIMIZE TABLE weibo_note;

-- 5.3 查看表大小和索引大小
SELECT
    TABLE_NAME AS '表名',
    ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS '总大小(MB)',
    ROUND(DATA_LENGTH / 1024 / 1024, 2) AS '数据大小(MB)',
    ROUND(INDEX_LENGTH / 1024 / 1024, 2) AS '索引大小(MB)',
    TABLE_ROWS AS '行数'
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'media_crawler'
  AND TABLE_NAME IN ('weibo_note_comment', 'weibo_note')
ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC;


-- -----------------------------------------------------------------------------
-- 6. 性能监控查询
-- -----------------------------------------------------------------------------

-- 6.1 查看慢查询（需要开启慢查询日志）
-- SET GLOBAL slow_query_log = 'ON';
-- SET GLOBAL long_query_time = 1;  -- 超过1秒的查询记录

-- 6.2 查看表锁情况
SHOW OPEN TABLES WHERE In_use > 0;

-- 6.3 查看当前连接数
SHOW PROCESSLIST;


-- -----------------------------------------------------------------------------
-- 7. 删除索引（如需回滚）
-- -----------------------------------------------------------------------------
-- 慎用！仅在索引导致性能下降时使用

-- DROP INDEX idx_note_id ON weibo_note_comment;
-- DROP INDEX idx_note_createtime ON weibo_note_comment;
-- DROP INDEX idx_user_id ON weibo_note_comment;
-- DROP INDEX idx_parent_comment ON weibo_note_comment;
-- DROP INDEX idx_create_time ON weibo_note_comment;


-- =============================================================================
-- 使用说明
-- =============================================================================
--
-- 1. 执行前请先备份数据库
-- 2. 在测试环境验证后再在生产环境执行
-- 3. 建议在业务低峰期执行（索引创建会锁表）
-- 4. 大表（>100万行）索引创建可能耗时较长，请耐心等待
-- 5. 执行完成后使用 EXPLAIN 验证查询是否使用了索引
--
-- =============================================================================
