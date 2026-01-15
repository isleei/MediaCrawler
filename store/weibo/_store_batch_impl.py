# -*- coding: utf-8 -*-
"""
批量写入优化的微博存储实现
用于解决评论抓取性能瓶颈
"""
import asyncio
from typing import Dict, List
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

import config
from base.base_crawler import AbstractStore
from database.models import WeiboNote, WeiboNoteComment, WeiboCreator
from database.db_session import get_session
from tools import utils


class WeiboBatchStoreImplement(AbstractStore):
    """批量写入优化的存储实现"""

    def __init__(self, batch_size: int = 100):
        """
        Args:
            batch_size: 批量写入的数量，默认100条
        """
        self.batch_size = batch_size
        self.comment_buffer: List[Dict] = []
        self.content_buffer: List[Dict] = []
        self.creator_buffer: List[Dict] = []
        self._lock = asyncio.Lock()

    async def store_comment(self, comment_item: Dict):
        """
        批量存储评论（缓冲后批量写入）
        """
        async with self._lock:
            self.comment_buffer.append(comment_item)

            # 达到批量大小，触发写入
            if len(self.comment_buffer) >= self.batch_size:
                await self._flush_comments()

    async def _flush_comments(self):
        """批量写入评论到数据库"""
        if not self.comment_buffer:
            return

        comments = self.comment_buffer.copy()
        self.comment_buffer.clear()

        async with get_session() as session:
            # 方式1：使用 INSERT ... ON DUPLICATE KEY UPDATE（MySQL）
            if config.DB_ENGINE == "mysql":
                await self._batch_upsert_mysql(session, comments)
            else:
                # 方式2：先查询已存在的，分批插入/更新
                await self._batch_upsert_generic(session, comments)

            await session.commit()
            utils.logger.info(f"[BatchStore] Flushed {len(comments)} comments to database")

    async def _batch_upsert_mysql(self, session, comments: List[Dict]):
        """MySQL 批量 UPSERT（使用 ON DUPLICATE KEY UPDATE）"""
        if not comments:
            return

        # 准备数据
        current_ts = utils.get_current_timestamp()
        for item in comments:
            item.setdefault("add_ts", current_ts)
            item["last_modify_ts"] = current_ts

        # 使用 MySQL INSERT ... ON DUPLICATE KEY UPDATE
        stmt = mysql_insert(WeiboNoteComment).values(comments)

        # 更新策略：除了 add_ts 和主键外的所有字段都更新
        update_dict = {
            c.name: c for c in stmt.inserted
            if c.name not in ["comment_id", "add_ts"]
        }

        stmt = stmt.on_duplicate_key_update(**update_dict)
        await session.execute(stmt)

    async def _batch_upsert_generic(self, session, comments: List[Dict]):
        """通用批量 UPSERT（先查询再分批处理）"""
        if not comments:
            return

        # 提取所有 comment_id
        comment_ids = [c["comment_id"] for c in comments]

        # 批量查询已存在的评论
        stmt = select(WeiboNoteComment.comment_id).where(
            WeiboNoteComment.comment_id.in_(comment_ids)
        )
        result = await session.execute(stmt)
        existing_ids = {row[0] for row in result.fetchall()}

        # 分离新增和更新
        to_insert = []
        to_update = []
        current_ts = utils.get_current_timestamp()

        for comment in comments:
            comment_id = comment["comment_id"]
            comment["last_modify_ts"] = current_ts

            if comment_id in existing_ids:
                to_update.append(comment)
            else:
                comment["add_ts"] = current_ts
                to_insert.append(comment)

        # 批量插入新评论
        if to_insert:
            session.add_all([WeiboNoteComment(**item) for item in to_insert])
            utils.logger.info(f"[BatchStore] Inserting {len(to_insert)} new comments")

        # 批量更新已存在评论（SQLAlchemy 2.0 支持 bulk_update_mappings）
        if to_update:
            await session.execute(
                WeiboNoteComment.__table__.update(),
                to_update
            )
            utils.logger.info(f"[BatchStore] Updating {len(to_update)} existing comments")

    async def store_content(self, content_item: Dict):
        """内容存储（可选批量优化）"""
        async with self._lock:
            self.content_buffer.append(content_item)

            if len(self.content_buffer) >= self.batch_size:
                await self._flush_contents()

    async def _flush_contents(self):
        """批量写入内容"""
        if not self.content_buffer:
            return

        contents = self.content_buffer.copy()
        self.content_buffer.clear()

        async with get_session() as session:
            current_ts = utils.get_current_timestamp()

            # 提取所有 note_id
            note_ids = [c["note_id"] for c in contents]

            # 批量查询已存在的
            stmt = select(WeiboNote.note_id).where(WeiboNote.note_id.in_(note_ids))
            result = await session.execute(stmt)
            existing_ids = {row[0] for row in result.fetchall()}

            # 分离新增和更新
            to_insert = []
            to_update = []

            for content in contents:
                note_id = content["note_id"]
                content["last_modify_ts"] = current_ts

                if note_id in existing_ids:
                    to_update.append(content)
                else:
                    content["add_ts"] = current_ts
                    to_insert.append(content)

            if to_insert:
                session.add_all([WeiboNote(**item) for item in to_insert])

            if to_update:
                await session.execute(
                    WeiboNote.__table__.update(),
                    to_update
                )

            await session.commit()
            utils.logger.info(f"[BatchStore] Flushed {len(contents)} contents to database")

    async def store_creator(self, creator: Dict):
        """创作者存储"""
        # 创作者数量较少，可以保持单条写入
        user_id = creator.get("user_id")
        async with get_session() as session:
            stmt = select(WeiboCreator).where(WeiboCreator.user_id == user_id)
            res = await session.execute(stmt)
            db_creator = res.scalar_one_or_none()

            current_ts = utils.get_current_timestamp()
            if db_creator:
                db_creator.last_modify_ts = current_ts
                for key, value in creator.items():
                    if hasattr(db_creator, key):
                        setattr(db_creator, key, value)
            else:
                creator["add_ts"] = current_ts
                creator["last_modify_ts"] = current_ts
                db_creator = WeiboCreator(**creator)
                session.add(db_creator)

            await session.commit()

    async def flush_all(self):
        """程序结束前，刷新所有缓冲区"""
        await self._flush_comments()
        await self._flush_contents()
        utils.logger.info("[BatchStore] All buffers flushed")


class WeiboBatchStoreWithCache(WeiboBatchStoreImplement):
    """
    带缓存的批量存储实现
    避免重复抓取已存在的评论
    """

    def __init__(self, batch_size: int = 100, enable_cache: bool = True):
        super().__init__(batch_size)
        self.enable_cache = enable_cache
        self.cached_comment_ids = set()
        self._cache_loaded = False

    async def _load_comment_cache(self, note_id: str):
        """加载已抓取的评论ID到缓存"""
        if not self.enable_cache:
            return

        async with get_session() as session:
            stmt = select(WeiboNoteComment.comment_id).where(
                WeiboNoteComment.note_id == note_id
            )
            result = await session.execute(stmt)
            existing_ids = {row[0] for row in result.fetchall()}
            self.cached_comment_ids.update(existing_ids)
            utils.logger.info(f"[CacheStore] Loaded {len(existing_ids)} cached comment IDs for note {note_id}")

    def is_comment_cached(self, comment_id: str) -> bool:
        """检查评论是否已缓存"""
        return comment_id in self.cached_comment_ids

    async def store_comment(self, comment_item: Dict):
        """存储评论（自动跳过已缓存的）"""
        comment_id = comment_item.get("comment_id")

        # 如果已缓存，跳过
        if self.enable_cache and comment_id in self.cached_comment_ids:
            return

        # 添加到缓存
        if self.enable_cache:
            self.cached_comment_ids.add(comment_id)

        # 批量存储
        await super().store_comment(comment_item)
