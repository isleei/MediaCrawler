#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查 MySQL 情感词典中的重复词"""

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

def check_duplicates():
    """检查重复词"""
    if not weibo_storage.mysql_enabled:
        print("MySQL 未启用")
        return

    db = weibo_storage._get_db()
    try:
        sentiment_types = ["positive", "negative", "negation", "degree", "stopwords"]

        print("=" * 60)
        print("检查 MySQL 情感词典中的重复词")
        print("=" * 60)
        print()

        for word_type in sentiment_types:
            # 查询重复词
            result = db.execute(text(f"""
                SELECT word, COUNT(*) as count
                FROM web_ui_sentiment_words
                WHERE word_type = :word_type AND platform = 'weibo'
                GROUP BY word
                HAVING COUNT(*) > 1
            """), {"word_type": word_type}).fetchall()

            if result:
                print(f"{word_type}: 发现 {len(result)} 个重复词")
                for word, count in result[:5]:  # 只显示前5个
                    print(f"  - {word}: {count} 次")
            else:
                print(f"{word_type}: 无重复词")

            # 统计总数和唯一数
            total = db.execute(text("""
                SELECT COUNT(*) FROM web_ui_sentiment_words
                WHERE word_type = :word_type AND platform = 'weibo'
            """), {"word_type": word_type}).scalar()

            unique = db.execute(text("""
                SELECT COUNT(DISTINCT word) FROM web_ui_sentiment_words
                WHERE word_type = :word_type AND platform = 'weibo'
            """), {"word_type": word_type}).scalar()

            print(f"  总数: {total}, 唯一: {unique}, 重复: {total - unique}")
            print()

    finally:
        db.close()

if __name__ == "__main__":
    check_duplicates()
