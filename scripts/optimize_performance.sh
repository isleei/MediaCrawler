#!/bin/bash

# =============================================================================
# 微博评论抓取性能优化 - 一键配置脚本（ES存储）
# 作用：自动优化配置文件，无需手动修改
# 预期效果：5-10倍性能提升
# =============================================================================

set -e  # 遇到错误立即退出

echo "======================================================================"
echo "微博评论抓取性能优化 - 一键配置脚本"
echo "======================================================================"
echo ""

# 检查文件是否存在
if [ ! -f "config/base_config.py" ]; then
    echo "❌ 错误：找不到 config/base_config.py"
    echo "   请确保在项目根目录下运行此脚本"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  警告：找不到 .env 文件"
    echo "   将从 .env.example 复制创建"
    cp .env.example .env
fi

# 备份原文件
BACKUP_DIR="config_backup_$(date +%Y%m%d_%H%M%S)"
echo "📦 创建备份目录：$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp config/base_config.py "$BACKUP_DIR/"
cp .env "$BACKUP_DIR/"
echo "✅ 已备份配置文件到 $BACKUP_DIR/"
echo ""

# 修改 config/base_config.py
echo "🔧 优化 config/base_config.py..."

# 1. 提高并发数
if grep -q "^MAX_CONCURRENCY_NUM = " config/base_config.py; then
    sed -i.bak 's/^MAX_CONCURRENCY_NUM = .*/MAX_CONCURRENCY_NUM = 10  # 性能优化：提高并发/' config/base_config.py
    echo "   ✓ 并发数提高到 10"
else
    echo "   ⚠️  未找到 MAX_CONCURRENCY_NUM 配置"
fi

# 2. 关闭二级评论
if grep -q "^ENABLE_GET_SUB_COMMENTS = " config/base_config.py; then
    sed -i.bak 's/^ENABLE_GET_SUB_COMMENTS = .*/ENABLE_GET_SUB_COMMENTS = False  # 性能优化：关闭二级评论/' config/base_config.py
    echo "   ✓ 关闭二级评论"
fi

# 3. 使用兼容存储
if grep -q "^SAVE_DATA_OPTION = " config/base_config.py; then
    sed -i.bak 's/^SAVE_DATA_OPTION = .*/SAVE_DATA_OPTION = "compat"  # 性能优化：使用兼容存储（支持ES）/' config/base_config.py
    echo "   ✓ 切换到兼容存储模式"
fi

rm -f config/base_config.py.bak
echo ""

# 修改 .env
echo "🔧 优化 .env..."

# 函数：更新或添加环境变量
update_env() {
    local key=$1
    local value=$2
    local comment=$3

    if grep -q "^${key}=" .env; then
        # 存在则更新
        sed -i.bak "s|^${key}=.*|${key}=${value}  # ${comment}|" .env
    elif grep -q "^#${key}=" .env; then
        # 存在注释行则启用
        sed -i.bak "s|^#${key}=.*|${key}=${value}  # ${comment}|" .env
    else
        # 不存在则添加
        echo "${key}=${value}  # ${comment}" >> .env
    fi
}

# ES 配置
update_env "ES_ENABLED" "1" "性能优化：启用ES"
echo "   ✓ 启用 ES 存储"

# MySQL 配置（关闭以提速）
update_env "WEIBO_CONTENT_MYSQL_ENABLED" "0" "性能优化：关闭MySQL内容存储"
update_env "WEIBO_COMMENT_MYSQL_ENABLED" "0" "性能优化：关闭MySQL评论存储"
echo "   ✓ 关闭 MySQL 存储（仅使用ES）"

# 热词优化
update_env "HOTWORDS_ENABLED" "1" "保留热词功能"
update_env "HOTWORDS_TOP_N" "10" "性能优化：减少热词数量"
echo "   ✓ 优化热词提取（从20降低到10）"

# 情感分析优化
update_env "SENTI_ENABLED" "1" "保留情感分析"
update_env "SENTI_USE_REDIS" "1" "性能优化：使用Redis缓存"
update_env "SENTI_CACHE_TTL" "300" "性能优化：延长缓存时间"
echo "   ✓ 启用情感分析 Redis 缓存"

# 关闭百度API意见抽取（非常耗时）
update_env "WEIBO_EXTRACTION_ENABLED" "0" "性能优化：关闭意见抽取（非常耗时）"
echo "   ✓ 关闭百度API意见抽取"

rm -f .env.bak
echo ""

# 显示优化结果
echo "======================================================================"
echo "✅ 性能优化配置完成！"
echo "======================================================================"
echo ""
echo "📊 优化内容："
echo "   • 并发数：1 → 10 （预计5-10倍提速）"
echo "   • 关闭二级评论（大幅减少抓取量）"
echo "   • 关闭MySQL存储（避免单条写入瓶颈）"
echo "   • 优化热词提取：20 → 10"
echo "   • 启用Redis缓存"
echo "   • 关闭百度API意见抽取"
echo ""
echo "📁 备份位置：$BACKUP_DIR/"
echo ""
echo "🚀 现在可以运行爬虫测试性能："
echo "   uv run main.py --platform wb --lt qrcode --type search"
echo ""
echo "📖 更多优化方案："
echo "   • 快速指南：docs/ES_PERFORMANCE_OPTIMIZATION.md"
echo "   • 完整方案：docs/comment_performance_optimization.md"
echo ""
echo "⚠️  注意事项："
echo "   • 如果需要恢复原配置，请从 $BACKUP_DIR/ 中复制回来"
echo "   • 如果需要MySQL存储，请手动修改 .env 中的 WEIBO_COMMENT_MYSQL_ENABLED=1"
echo "   • 确保 ES 服务正常运行（检查 ES_HOSTS 配置）"
echo ""
echo "======================================================================"
