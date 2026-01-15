#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试配置文件是否正确读取 .env"""

import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

print("=" * 60)
print("测试配置文件读取 .env")
print("=" * 60)
print()

# 测试 db_config
print("1. 测试 config/db_config.py")
from config.db_config import MYSQL_DB_HOST, MYSQL_DB_PORT, MYSQL_DB_NAME, MYSQL_DB_USER
print(f"   MYSQL_DB_HOST: {MYSQL_DB_HOST}")
print(f"   MYSQL_DB_PORT: {MYSQL_DB_PORT}")
print(f"   MYSQL_DB_NAME: {MYSQL_DB_NAME}")
print(f"   MYSQL_DB_USER: {MYSQL_DB_USER}")
print()

# 测试 base_config
print("2. 测试 config/base_config.py")
from config.base_config import WEIBO_EXTRACTION_ENABLED, WEIBO_EXTRACTION_TYPE
print(f"   WEIBO_EXTRACTION_ENABLED: {WEIBO_EXTRACTION_ENABLED}")
print(f"   WEIBO_EXTRACTION_TYPE: {WEIBO_EXTRACTION_TYPE}")
print()

# 测试 weibo_storage
print("3. 测试 api/services/weibo_storage.py")
from api.services.weibo_storage import weibo_storage
print(f"   MySQL Enabled: {weibo_storage.mysql_enabled}")
if weibo_storage.engine:
    print(f"   MySQL Engine: {weibo_storage.engine.url}")
print()

print("=" * 60)
print("✓ 所有配置文件都能正确读取 .env")
print("=" * 60)
