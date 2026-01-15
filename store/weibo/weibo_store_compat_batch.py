# -*- coding: utf-8 -*-
"""
Elasticsearch 批量写入优化的微博存储实现
用于解决 ES 评论抓取性能瓶颈
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, List
from urllib import request as urlrequest
from urllib.parse import quote

from tools import utils


class ESBulkHelper:
    """Elasticsearch Bulk API 批量写入助手"""

    def __init__(self, es_base_url: str, batch_size: int = 100):
        """
        Args:
            es_base_url: ES 基础 URL，如 http://127.0.0.1:9200
            batch_size: 批量大小，默认 100 条
        """
        self.es_base = es_base_url.rstrip("/")
        self.batch_size = batch_size
        self.buffer: List[Dict] = []  # 缓冲区
        self._lock = asyncio.Lock()

    async def index(self, index_name: str, doc_id: str, doc: Dict):
        """
        添加文档到批量缓冲区

        Args:
            index_name: 索引名称
            doc_id: 文档ID
            doc: 文档内容
        """
        async with self._lock:
            # 添加 action 和 doc
            self.buffer.append({
                "action": {"index": {"_index": index_name, "_id": doc_id}},
                "doc": doc
            })

            # 达到批量大小，触发写入
            if len(self.buffer) >= self.batch_size:
                await self._flush()

    async def _flush(self):
        """批量写入到 ES"""
        if not self.buffer:
            return

        items = self.buffer.copy()
        self.buffer.clear()

        try:
            # 构建 Bulk API 请求体
            # 格式：action_line\ndoc_line\naction_line\ndoc_line\n...
            lines = []
            for item in items:
                lines.append(json.dumps(item["action"], ensure_ascii=False))
                lines.append(json.dumps(item["doc"], ensure_ascii=False, default=self._json_default))

            body = "\n".join(lines) + "\n"

            # 调用 Bulk API
            url = f"{self.es_base}/_bulk"
            headers = {
                "Content-Type": "application/x-ndjson",
                "Accept": "application/json"
            }

            req = urlrequest.Request(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                method="POST"
            )

            with urlrequest.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                if result.get("errors"):
                    # 有错误，记录日志
                    error_count = sum(1 for item in result.get("items", []) if item.get("index", {}).get("error"))
                    utils.logger.warning(f"[ESBulkHelper] Bulk indexing completed with {error_count} errors")
                else:
                    utils.logger.info(f"[ESBulkHelper] Successfully indexed {len(items)} documents")

        except Exception as e:
            utils.logger.error(f"[ESBulkHelper] Bulk indexing failed: {e}")
            # 失败后可以选择重试或记录失败的文档
            raise

    async def flush_all(self):
        """刷新所有缓冲区数据"""
        await self._flush()
        utils.logger.info("[ESBulkHelper] All buffers flushed")

    def _json_default(self, obj):
        """JSON 序列化默认处理"""
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return str(obj)


class WeiboCompatStoreBatchOptimized:
    """
    优化版的微博兼容存储实现
    支持 MySQL 和 ES 的批量写入
    """

    def __init__(self,
                 batch_size: int = 100,
                 enable_comment_cache: bool = True,
                 enable_hotwords_cache: bool = True):
        """
        Args:
            batch_size: 批量大小
            enable_comment_cache: 是否启用评论缓存（避免重复处理）
            enable_hotwords_cache: 是否启用热词缓存（避免重复分词）
        """
        self.batch_size = batch_size
        self.enable_comment_cache = enable_comment_cache
        self.enable_hotwords_cache = enable_hotwords_cache

        # MySQL 批量缓冲区
        self.comment_buffer: List[Dict] = []
        self.hotword_buffer: List[Dict] = []

        # ES 批量助手
        import os
        es_hosts = os.getenv("ES_HOSTS", "http://127.0.0.1:9200").split(",")
        es_base = (es_hosts[0].strip() if es_hosts else "http://127.0.0.1:9200").rstrip("/")
        self.es_bulk = ESBulkHelper(es_base, batch_size=batch_size)

        # 缓存
        self.comment_ids_cache = set() if enable_comment_cache else None
        self.hotwords_cache = {} if enable_hotwords_cache else None

        self._lock = asyncio.Lock()

    async def store_comment(self, comment_item: dict):
        """
        批量存储评论（优化版）
        """
        comment_id = comment_item.get("comment_id")
        note_id = comment_item.get("note_id")

        if not comment_id or not note_id:
            return

        # 缓存检查：跳过已处理的评论
        if self.comment_ids_cache is not None:
            if comment_id in self.comment_ids_cache:
                return  # 已处理，跳过
            self.comment_ids_cache.add(comment_id)

        # 构建文档 ID
        content_id = self._build_content_id(note_id)
        pinglun_id = f"{content_id}_{comment_id}"

        # 准备数据
        payload = self._prepare_comment_payload(comment_item, content_id, pinglun_id)

        # 热词提取（使用缓存）
        comment_text = payload["pinglun_text"]
        hotwords = await self._extract_hotwords_cached(comment_text)

        # 添加到批量缓冲区
        async with self._lock:
            self.comment_buffer.append({
                "pinglun_id": pinglun_id,
                "payload": payload,
                "hotwords": hotwords
            })

            # 达到批量大小，触发写入
            if len(self.comment_buffer) >= self.batch_size:
                await self._flush_comments()

    async def _flush_comments(self):
        """批量写入评论到 MySQL 和 ES"""
        if not self.comment_buffer:
            return

        comments = self.comment_buffer.copy()
        self.comment_buffer.clear()

        import os

        # 1. 批量写入 MySQL（如果启用）
        if os.getenv("WEIBO_COMMENT_MYSQL_ENABLED", "0") in ("1", "true", "True"):
            await self._batch_write_mysql(comments)

        # 2. 批量写入 ES
        await self._batch_write_es(comments)

        utils.logger.info(f"[WeiboCompatStoreBatch] Flushed {len(comments)} comments")

    async def _batch_write_mysql(self, comments: List[Dict]):
        """批量写入 MySQL"""
        # TODO: 实现 MySQL 批量写入逻辑
        # 类似于之前的 WeiboBatchStoreImplement._batch_upsert_generic
        pass

    async def _batch_write_es(self, comments: List[Dict]):
        """批量写入 ES"""
        import os
        index_name = os.getenv("ES_INDEX_PINGLUN", "weibopinglun")

        for comment in comments:
            pinglun_id = comment["pinglun_id"]
            payload = comment["payload"]

            # 添加到 ES 批量缓冲区
            await self.es_bulk.index(index_name, pinglun_id, payload)

    async def _extract_hotwords_cached(self, text: str) -> List[Dict]:
        """带缓存的热词提取"""
        if not text:
            return []

        # 检查缓存
        if self.hotwords_cache is not None:
            if text in self.hotwords_cache:
                return self.hotwords_cache[text]

        # 提取热词（同步操作，放到线程池执行）
        hotwords = await asyncio.to_thread(self._extract_hotwords_sync, text)

        # 缓存结果
        if self.hotwords_cache is not None:
            # 限制缓存大小（最多 10000 条）
            if len(self.hotwords_cache) > 10000:
                # 清空一半缓存
                keys = list(self.hotwords_cache.keys())
                for key in keys[:5000]:
                    del self.hotwords_cache[key]

            self.hotwords_cache[text] = hotwords

        return hotwords

    def _extract_hotwords_sync(self, text: str) -> List[Dict]:
        """同步的热词提取（CPU 密集操作）"""
        # TODO: 实现热词提取逻辑
        # 参考 weibo_store_compat.py:597-631
        import jieba.analyse
        import os

        top_n = int(os.getenv("HOTWORDS_TOP_N", "20"))
        keywords = jieba.analyse.extract_tags(text, topK=top_n, withWeight=True)

        return [
            {"word": word, "weight": weight}
            for word, weight in keywords
        ]

    def _prepare_comment_payload(self, comment_item: dict, content_id: str, pinglun_id: str) -> Dict:
        """准备评论数据"""
        now = datetime.now()
        created_at = self._parse_datetime(comment_item.get("create_date_time")) or now
        update_at = now

        comment_text = self._clean_text(comment_item.get("content", ""))
        if len(comment_text) > 5000:
            comment_text = comment_text[:5000]

        return {
            "pinglun_id": pinglun_id,
            "pinglun_parent_id": comment_item.get("parent_comment_id") or "",
            "pinglun_text": comment_text,
            "created_at": created_at,
            "sub_pinglun_count": str(comment_item.get("sub_comment_count", 0) or 0),
            "like_count": str(comment_item.get("comment_like_count", 0) or 0),
            "floor_number": str(comment_item.get("floor_number", 0) or 0),
            "pinglun_user": comment_item.get("nickname", ""),
            "weibo_content_id": content_id,
            "senti_score": int(comment_item.get("senti_score", 0) or 0),
            "update_at": update_at,
        }

    def _build_content_id(self, note_id: str) -> str:
        """构建内容 ID"""
        # TODO: 实现与原代码相同的逻辑
        return f"weibocontent_{note_id}"

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        import re
        return re.sub(r"<[^>]+>", "", text)

    def _parse_datetime(self, value) -> datetime:
        """解析日期时间"""
        if not value:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        # TODO: 实现更完整的解析逻辑
        return datetime.now()

    async def flush_all(self):
        """刷新所有缓冲区"""
        await self._flush_comments()
        await self.es_bulk.flush_all()
        utils.logger.info("[WeiboCompatStoreBatch] All buffers flushed")
