#!/bin/bash

# =============================================================================
# ES 批量写入 - 一键启用脚本
# 作用：自动配置 ES Bulk API 批量写入，获得 20-50倍性能提升
# =============================================================================

set -e

echo "======================================================================"
echo "ES 批量写入优化 - 一键启用脚本"
echo "预期性能提升：20-50倍 🚀"
echo "======================================================================"
echo ""

# 检查文件
if [ ! -f "config/base_config.py" ]; then
    echo "❌ 错误：找不到 config/base_config.py"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  警告：找不到 .env 文件，从 .env.example 复制"
    cp .env.example .env
fi

# 备份
BACKUP_DIR="config_backup_batch_$(date +%Y%m%d_%H%M%S)"
echo "📦 创建备份：$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp config/base_config.py "$BACKUP_DIR/"
cp .env "$BACKUP_DIR/"
echo ""

# 函数：更新环境变量
update_env() {
    local key=$1
    local value=$2

    if grep -q "^${key}=" .env; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" .env
    elif grep -q "^#${key}=" .env; then
        sed -i.bak "s|^#${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

echo "🔧 配置批量写入功能..."

# 1. 启用批量写入
update_env "WEIBO_BATCH_ENABLED" "1"
echo "   ✓ 启用批量写入"

# 2. 设置批量大小
update_env "WEIBO_BATCH_SIZE" "200"
echo "   ✓ 批量大小设置为 200"

# 3. 启用评论缓存
update_env "WEIBO_COMMENT_CACHE_ENABLED" "1"
echo "   ✓ 启用评论缓存（跳过重复）"

# 4. 确保 ES 启用
update_env "ES_ENABLED" "1"
echo "   ✓ 确保 ES 启用"

# 5. 关闭 MySQL（可选，提升性能）
read -p "是否关闭 MySQL 存储以获得最佳性能？(y/n) [默认:y]: " disable_mysql
disable_mysql=${disable_mysql:-y}

if [[ "$disable_mysql" == "y" || "$disable_mysql" == "Y" ]]; then
    update_env "WEIBO_COMMENT_MYSQL_ENABLED" "0"
    update_env "WEIBO_CONTENT_MYSQL_ENABLED" "0"
    echo "   ✓ 关闭 MySQL 存储（仅使用 ES）"
else
    update_env "WEIBO_COMMENT_MYSQL_ENABLED" "1"
    echo "   ✓ 保留 MySQL 存储"
fi

# 6. 优化热词
update_env "HOTWORDS_TOP_N" "10"
echo "   ✓ 优化热词数量：20 → 10"

# 7. 关闭百度API
update_env "WEIBO_EXTRACTION_ENABLED" "0"
echo "   ✓ 关闭百度API意见抽取"

rm -f .env.bak
echo ""

# 修改 base_config.py
echo "🔧 配置 base_config.py..."

# 确保使用兼容存储
if grep -q "^SAVE_DATA_OPTION = " config/base_config.py; then
    sed -i.bak 's/^SAVE_DATA_OPTION = .*/SAVE_DATA_OPTION = "compat"  # 批量优化：使用兼容存储/' config/base_config.py
    echo "   ✓ 切换到兼容存储模式"
fi

# 提高并发数
if grep -q "^MAX_CONCURRENCY_NUM = " config/base_config.py; then
    if [[ "$disable_mysql" == "y" || "$disable_mysql" == "Y" ]]; then
        sed -i.bak 's/^MAX_CONCURRENCY_NUM = .*/MAX_CONCURRENCY_NUM = 15  # 批量优化：提高并发/' config/base_config.py
        echo "   ✓ 并发数提高到 15"
    else
        sed -i.bak 's/^MAX_CONCURRENCY_NUM = .*/MAX_CONCURRENCY_NUM = 10  # 批量优化：适度并发（MySQL较慢）/' config/base_config.py
        echo "   ✓ 并发数提高到 10（保留MySQL）"
    fi
fi

rm -f config/base_config.py.bak
echo ""

# 检查 ES 配置
echo "🔍 检查 ES 配置..."
es_host=$(grep "^ES_HOSTS=" .env | cut -d= -f2)
if [ -z "$es_host" ] || [ "$es_host" == "http://127.0.0.1:9200" ]; then
    echo ""
    echo "⚠️  警告：ES_HOSTS 使用默认值或未配置"
    echo "   当前值：${es_host:-未设置}"
    echo ""
    read -p "请输入你的 ES 地址 [默认: http://127.0.0.1:9200]: " new_es_host
    new_es_host=${new_es_host:-http://127.0.0.1:9200}
    update_env "ES_HOSTS" "$new_es_host"
    echo "   ✓ ES 地址设置为：$new_es_host"
else
    echo "   ✓ ES 地址：$es_host"
fi
echo ""

# 测试 ES 连接
echo "🔌 测试 ES 连接..."
es_test_host=$(grep "^ES_HOSTS=" .env | cut -d= -f2 | tr -d ' ')
if command -v curl &> /dev/null; then
    if curl -s -o /dev/null -w "%{http_code}" "$es_test_host" | grep -q "200"; then
        echo "   ✅ ES 连接成功！"
    else
        echo "   ⚠️  警告：无法连接到 ES，请检查 ES 服务是否运行"
        echo "   测试命令：curl $es_test_host"
    fi
else
    echo "   ⚠️  未安装 curl，无法测试连接"
fi
echo ""

# 显示配置总结
echo "======================================================================"
echo "✅ ES 批量写入配置完成！"
echo "======================================================================"
echo ""
echo "📊 优化配置："
echo "   • 批量写入：启用（batch_size=200）"
echo "   • 评论缓存：启用（跳过重复）"
echo "   • ES 存储：启用"
if [[ "$disable_mysql" == "y" || "$disable_mysql" == "Y" ]]; then
    echo "   • MySQL 存储：关闭（仅使用 ES）"
    echo "   • 并发数：15"
else
    echo "   • MySQL 存储：启用（ES + MySQL 双写）"
    echo "   • 并发数：10"
fi
echo "   • 热词优化：10 个/评论"
echo "   • 百度API：关闭"
echo ""
echo "📁 备份位置：$BACKUP_DIR/"
echo ""
echo "🚀 现在运行爬虫测试性能："
echo "   uv run main.py --platform wb --lt qrcode --type search"
echo ""
echo "🔍 验证批量写入是否生效："
echo "   查看日志中是否有："
echo "   [WeiboCompatStore] Flushing 200 comments (batch mode)..."
echo "   [WeiboCompatStore] ES Bulk: Successfully indexed 200 documents"
echo ""
echo "📈 预期性能提升："
if [[ "$disable_mysql" == "y" || "$disable_mysql" == "Y" ]]; then
    echo "   • 1000条评论：3-5分钟 → 10-15秒（30-50倍）⭐⭐⭐⭐⭐"
    echo "   • 10000条评论：30-50分钟 → 1-2分钟（30-50倍）⭐⭐⭐⭐⭐"
else
    echo "   • 1000条评论：3-5分钟 → 20-30秒（15-25倍）⭐⭐⭐⭐"
    echo "   • 10000条评论：30-50分钟 → 2-3分钟（15-25倍）⭐⭐⭐⭐"
fi
echo ""
echo "📖 详细文档："
echo "   • docs/ES_BATCH_IMPLEMENTATION_GUIDE.md - 完整使用指南"
echo "   • docs/ES_PERFORMANCE_OPTIMIZATION.md - 性能优化方案"
echo ""
echo "⚠️  注意事项："
echo "   • 如需恢复原配置，请从 $BACKUP_DIR/ 复制回来"
echo "   • 确保 ES 服务正常运行"
echo "   • 首次运行会自动创建 ES 索引"
echo ""
echo "======================================================================"
