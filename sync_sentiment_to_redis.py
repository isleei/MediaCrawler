#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""同步 MySQL 情感词典到 Redis"""

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

def sync_sentiment_to_redis():
    """同步情感词典到 Redis"""
    if not weibo_storage.mysql_enabled:
        print("MySQL 未启用，无法同步")
        return

    print("=" * 60)
    print("同步 MySQL 情感词典到 Redis")
    print("=" * 60)
    print()

    sentiment_types = ["positive", "negative", "negation", "degree", "stopwords"]

    for word_type in sentiment_types:
        print(f"同步 {word_type}...", end="", flush=True)
        try:
            words = weibo_storage.list_sentiment_words(word_type)
            redis_key = f"weibo:senti:{word_type}"

            # 清空 Redis 中的旧数据
            weibo_storage.redis_client.delete(redis_key)

            # 批量添加新数据（每批1000个）
            if words:
                batch_size = 1000
                for i in range(0, len(words), batch_size):
                    batch = words[i:i+batch_size]
                    weibo_storage.redis_client.sadd(redis_key, *batch)

            print(f" ✓ ({len(words)} 个词)")
        except Exception as e:
            print(f" ✗ 失败: {e}")

    print()
    print("=" * 60)
    print("同步完成！")
    print("=" * 60)

    # 验证同步结果
    print()
    print("验证同步结果：")
    for word_type in sentiment_types:
        redis_key = f"weibo:senti:{word_type}"
        count = weibo_storage.redis_client.scard(redis_key)
        print(f"  {word_type}: {count} 个词")

if __name__ == "__main__":
    try:
        sync_sentiment_to_redis()
    except Exception as e:
        print(f"同步失败: {e}")
        import traceback
        traceback.print_exc()
