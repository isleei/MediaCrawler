# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/db_session.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base
import config
from config.db_config import mysql_db_config, sqlite_db_config

# Keep a cache of engines
_engines = {}


def _build_mysql_url(with_db: bool = True) -> str:
    user = quote_plus(str(mysql_db_config["user"]))
    password = quote_plus(str(mysql_db_config["password"]))
    host = mysql_db_config["host"]
    port = int(mysql_db_config["port"])
    base = f"mysql+asyncmy://{user}:{password}@{host}:{port}"
    if with_db:
        return f"{base}/{mysql_db_config['db_name']}?charset=utf8mb4"
    return f"{base}/?charset=utf8mb4"

async def create_database_if_not_exists(db_type: str):
    if db_type == "mysql" or db_type == "db":
        import asyncmy
        conn = await asyncmy.connect(
            host=mysql_db_config["host"],
            port=int(mysql_db_config["port"]),
            user=mysql_db_config["user"],
            password=mysql_db_config["password"],
        )
        try:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "CREATE DATABASE IF NOT EXISTS "
                    f"{mysql_db_config['db_name']} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            await conn.commit()
        finally:
            if hasattr(conn, "ensure_closed"):
                await conn.ensure_closed()
            else:
                conn.close()

def get_async_engine(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION

    if db_type in _engines:
        return _engines[db_type]

    if db_type in ["json", "csv"]:
        return None

    if db_type == "sqlite":
        db_url = f"sqlite+aiosqlite:///{sqlite_db_config['db_path']}"
        engine = create_async_engine(db_url, echo=False)
    elif db_type == "mysql" or db_type == "db":
        engine = create_async_engine(_build_mysql_url(with_db=True), echo=False, pool_pre_ping=True)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    _engines[db_type] = engine
    return engine

async def create_tables(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION
    
    # Try to create DB if using mysql
    try:
        if db_type in ["mysql", "db"]:
            await create_database_if_not_exists(db_type)
    except Exception as e:
        print(f"Warning: Failed to ensure database existence: {e}")

    engine = get_async_engine(db_type)
    if engine:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def get_session() -> AsyncSession:
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        yield None
        return
    
    AsyncSessionFactory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    session = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e
    finally:
        await session.close()
