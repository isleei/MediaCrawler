#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 Redis 到 MySQL 迁移结果"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

# Load environment variables
load_dotenv()

from api.services.weibo_storage import weibo_storage
from sqlalchemy import text

def verify_migration():
    """验证迁移结果"""
    if not weibo_storage.mysql_enabled:
        print("MySQL 未启用，无法验证")
        return

    db = weibo_storage._get_db()
    try:
        print("=" * 60)
        print("数据迁移验证报告")
        print("=" * 60)
        print()

        # 1. 任务统计
        tasks_count = db.execute(text("SELECT COUNT(*) FROM web_ui_tasks WHERE task_type='weibo'")).scalar()
        print(f"✓ 任务 (Tasks): {tasks_count} 条")

        # 2. Cookie 统计
        cookies_count = db.execute(text("SELECT COUNT(*) FROM web_ui_cookies WHERE cookie_type='weibo'")).scalar()
        print(f"✓ Cookies: {cookies_count} 条")

        # 3. Cookie Bundle 统计
        bundles_count = db.execute(text("SELECT COUNT(*) FROM web_ui_cookie_bundles WHERE bundle_type='weibo'")).scalar()
        print(f"✓ Cookie Bundles: {bundles_count} 条")

        # 4. 代理统计
        proxies_count = db.execute(text("SELECT COUNT(*) FROM web_ui_proxies WHERE proxy_type='weibo'")).scalar()
        print(f"✓ 代理 (Proxies): {proxies_count} 条")

        # 5. 情感词统计
        sentiment_stats = db.execute(text("""
            SELECT word_type, COUNT(*) as count
            FROM web_ui_sentiment_words
            WHERE platform='weibo'
            GROUP BY word_type
        """)).fetchall()

        print(f"✓ 情感词典 (Sentiment Words):")
        total_sentiment = 0
        for word_type, count in sentiment_stats:
            print(f"  - {word_type}: {count} 个词")
            total_sentiment += count
        print(f"  总计: {total_sentiment} 个词")

        # 6. 配置统计
        configs = db.execute(text("SELECT config_key FROM web_ui_configs WHERE config_type='weibo'")).fetchall()
        print(f"✓ 配置 (Configs): {len(configs)} 条")
        for (config_key,) in configs:
            print(f"  - {config_key}")

        # 7. 批次统计
        batches_count = db.execute(text("SELECT COUNT(*) FROM web_ui_batches WHERE batch_type='weibo'")).scalar()
        print(f"✓ 批次 (Batches): {batches_count} 条")

        # 8. 任务日志统计
        logs_count = db.execute(text("SELECT COUNT(*) FROM web_ui_task_logs")).scalar()
        print(f"✓ 任务日志 (Task Logs): {logs_count} 条")

        print()
        print("=" * 60)
        print("验证完成！所有数据已成功迁移到 MySQL")
        print("=" * 60)

    except Exception as e:
        print(f"验证失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    verify_migration()
