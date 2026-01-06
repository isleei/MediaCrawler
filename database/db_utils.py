# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/db_utils.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
Database utility functions for creating SQLAlchemy engines with proper handling of special characters in passwords.
"""

import os
from sqlalchemy import create_engine


def create_mysql_engine_safe(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    charset: str = "utf8mb4",
    pool_pre_ping: bool = False,
    pool_recycle: int = 3600,
    pool_size: int = 5,
    max_overflow: int = 10,
    connect_timeout: int = 10,
):
    """
    Create a MySQL SQLAlchemy engine with safe handling of special characters in password.

    This function uses a custom creator to bypass SQLAlchemy's URL parsing,
    which can fail when passwords contain special characters like @, #, $, %.

    Args:
        host: MySQL server host
        port: MySQL server port
        user: MySQL username
        password: MySQL password (can contain special characters)
        database: Database name
        charset: Character set (default: utf8mb4)
        pool_pre_ping: Enable connection pool pre-ping (default: False)
        pool_recycle: Connection recycle time in seconds (default: 3600)
        pool_size: Connection pool size (default: 5)
        max_overflow: Max overflow connections (default: 10)
        connect_timeout: Connection timeout in seconds (default: 10)

    Returns:
        SQLAlchemy Engine instance
    """
    import pymysql

    def get_connection():
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
            connect_timeout=connect_timeout,
        )

    return create_engine(
        "mysql+pymysql://",
        creator=get_connection,
        pool_pre_ping=pool_pre_ping,
        pool_recycle=pool_recycle,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


def create_mysql_engine_from_env(
    host_env: str = "MYSQL_DB_HOST",
    port_env: str = "MYSQL_DB_PORT",
    user_env: str = "MYSQL_DB_USER",
    password_env: str = "MYSQL_DB_PWD",
    database_env: str = "MYSQL_DB_NAME",
    charset_env: str = "MYSQL_CHARSET",
    **kwargs
):
    """
    Create a MySQL SQLAlchemy engine from environment variables.

    Args:
        host_env: Environment variable name for host (default: MYSQL_DB_HOST)
        port_env: Environment variable name for port (default: MYSQL_DB_PORT)
        user_env: Environment variable name for user (default: MYSQL_DB_USER)
        password_env: Environment variable name for password (default: MYSQL_DB_PWD)
        database_env: Environment variable name for database (default: MYSQL_DB_NAME)
        charset_env: Environment variable name for charset (default: MYSQL_CHARSET)
        **kwargs: Additional arguments passed to create_mysql_engine_safe

    Returns:
        SQLAlchemy Engine instance
    """
    host = os.getenv(host_env, "127.0.0.1")
    port = int(os.getenv(port_env, "3306"))
    user = os.getenv(user_env, "root")
    password = os.getenv(password_env, "")
    database = os.getenv(database_env, "yuqing")
    charset = os.getenv(charset_env, "utf8mb4")

    return create_mysql_engine_safe(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset=charset,
        **kwargs
    )
