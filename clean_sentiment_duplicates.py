#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理 MySQL 情感词典中的重复词"""

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

def clean_duplicates():
    """清理重复词"""
    if not weibo_storage.mysql_enabled:
        print("MySQL 未启用")
        return

    db = weibo_storage._get_db()
    try:
        sentiment_types = ["positive", "negative", "negation", "degree", "stopwords"]

        print("=" * 60)
        print("清理 MySQL 情感词典中的重复词")
        print("=" * 60)
        print()

        for word_type in sentiment_types:
            print(f"处理 {word_type}...", end="", flush=True)

            # 查询重复词
            duplicates = db.execute(text("""
                SELECT word, COUNT(*) as count
                FROM web_ui_sentiment_words
                WHERE word_type = :word_type AND platform = 'weibo'
                GROUP BY word
                HAVING COUNT(*) > 1
            """), {"word_type": word_type}).fetchall()

            if not duplicates:
                print(" 无重复词")
                continue

            # 删除重复词，只保留一个
            deleted_count = 0
            for word, count in duplicates:
                # 获取所有重复的 ID
                ids = db.execute(text("""
                    SELECT id FROM web_ui_sentiment_words
                    WHERE word_type = :word_type AND word = :word AND platform = 'weibo'
                    ORDER BY id
                """), {"word_type": word_type, "word": word}).fetchall()

                # 保留第一个，删除其他
                if len(ids) > 1:
                    ids_to_delete = [id[0] for id in ids[1:]]
                    db.execute(text("""
                        DELETE FROM web_ui_sentiment_words
                        WHERE id IN :ids
                    """), {"ids": tuple(ids_to_delete)})
                    deleted_count += len(ids_to_delete)

            db.commit()
            print(f" ✓ 删除 {deleted_count} 个重复词")

        print()
        print("=" * 60)
        print("清理完成！")
        print("=" * 60)

        # 验证结果
        print()
        print("验证结果：")
        for word_type in sentiment_types:
            total = db.execute(text("""
                SELECT COUNT(*) FROM web_ui_sentiment_words
                WHERE word_type = :word_type AND platform = 'weibo'
            """), {"word_type": word_type}).scalar()
            print(f"  {word_type}: {total} 个词")

    except Exception as e:
        db.rollback()
        print(f"清理失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    clean_duplicates()
