# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/weibo/weibo_store_compat.py
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

import asyncio
import json
import os
import re
import socket
import threading
import time
from datetime import datetime
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import quote

import jieba
from sqlalchemy.orm import sessionmaker
import redis

import config
from base.base_crawler import AbstractStore
from database.models import (
    WebExtraction,
    WeiboContent,
    WeiboContentHotword,
    WeiboPinglun,
    WeiboPinglunHotword,
)
from tools import utils
from var import source_keyword_var
from .weibo_es_mappings import _weibocontent_mappings, _weibopinglun_mappings


class WeiboCompatStoreImplement(AbstractStore):
    _MAX_TEXT_LENGTH = 5000

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._non_word = re.compile(r"[^\u4e00-\u9fa5a-zA-Z]")
        self._html = re.compile(r"<[^>]+>")
        self._extraction_html = re.compile(
            r"<[^>]+>|http://t.cn/(\w+)|\[.+\]|#[^#]+#|\u0040.*\u97f3\u4e50"
        )
        self._stopwords = None
        self._engine = None
        self._session_factory = None
        self._es_base = None
        self._es_enabled = os.getenv("ES_ENABLED", "1") in ("1", "true", "True")
        legacy_mysql_flag = os.getenv("WEIBO_MYSQL_ENABLED")
        if legacy_mysql_flag is not None:
            legacy_enabled = legacy_mysql_flag in ("1", "true", "True")
            self._content_mysql_enabled = legacy_enabled
            self._comment_mysql_enabled = legacy_enabled
        else:
            self._content_mysql_enabled = os.getenv(
                "WEIBO_CONTENT_MYSQL_ENABLED", "0"
            ) in (
                "1",
                "true",
                "True",
            )
            self._comment_mysql_enabled = os.getenv(
                "WEIBO_COMMENT_MYSQL_ENABLED", "0"
            ) in (
                "1",
                "true",
                "True",
            )
        self._extraction_client = None
        self._extraction_ready = False
        self._extraction_lock = threading.Lock()
        self._extraction_last_ts = 0.0
        self._stats_client = None
        self._stats_key = ""

        # 批量写入配置
        self._batch_enabled = os.getenv("WEIBO_BATCH_ENABLED", "0") in ("1", "true", "True")
        self._batch_size = int(os.getenv("WEIBO_BATCH_SIZE", "100"))
        self._comment_buffer = []
        self._content_buffer = []
        self._es_bulk_buffer = []
        self._batch_lock = threading.Lock()
        self._comment_cache = set() if os.getenv("WEIBO_COMMENT_CACHE_ENABLED", "0") in ("1", "true", "True") else None

        self._init_db()
        self._init_stats_client()
        self._init_extraction_client()
        self._init_es()

    async def store_content(self, content_item: dict):
        await asyncio.to_thread(self._store_content_sync, content_item)

    async def store_comment(self, comment_item: dict):
        await asyncio.to_thread(self._store_comment_sync, comment_item)

    async def store_creator(self, creator: dict):
        # 当前兼容存储不处理创作者信息
        return

    def _init_db(self):
        from database.db_utils import create_mysql_engine_safe
        from config.db_config import mysql_db_config

        host = mysql_db_config["host"]
        port = int(mysql_db_config["port"])
        user = mysql_db_config["user"]
        password = mysql_db_config["password"]
        dbname = mysql_db_config["db_name"]
        charset = os.getenv("MYSQL_CHARSET", "utf8mb4")

        # Use shared config with safe password handling
        self._engine = create_mysql_engine_safe(
            host=host,
            port=port,
            user=user,
            password=password,
            database=dbname,
            charset=charset,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def _init_es(self):
        if not self._es_enabled:
            return
        hosts = os.getenv("ES_HOSTS", "").split(",")
        host = (hosts[0].strip() if hosts and hosts[0].strip() else "").rstrip("/")
        if not host:
            host = "http://127.0.0.1:9200"
        self._es_base = host
        self._ensure_index(
            os.getenv("ES_INDEX_WEIBO", "weibocontent"), _weibocontent_mappings
        )
        self._ensure_index(
            os.getenv("ES_INDEX_PINGLUN", "weibopinglun"), _weibopinglun_mappings
        )

    def _init_stats_client(self):
        task_id = os.getenv("CRAWLER_TASK_ID", "").strip()
        if not task_id:
            return
        try:
            self._stats_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
            prefix = os.getenv("TASK_STATS_PREFIX", "weibo:task:stats:")
            self._stats_key = f"{prefix}{task_id}"
        except Exception as exc:
            utils.logger.warning("[store.weibo.stats] init failed: %s", exc)
            self._stats_client = None
            self._stats_key = ""

    def _incr_stat(self, field):
        task_id = os.getenv("CRAWLER_TASK_ID", "").strip()
        if not task_id or not self._session_factory:
            return
        try:
            from database.models import WebUITask

            session = self._session_factory()
            try:
                task = (
                    session.query(WebUITask)
                    .filter(WebUITask.task_id == task_id)
                    .first()
                )
                if task:
                    if hasattr(task, field):
                        setattr(task, field, getattr(task, field, 0) + 1)
                        # Also increment items_count for total
                        if field in ["content_inserted", "comment_inserted"]:
                            task.items_count = (task.items_count or 0) + 1
                        session.commit()
            finally:
                session.close()
        except Exception as exc:
            utils.logger.warning("[store.weibo.stats] MySQL update failed: %s", exc)

    def _init_extraction_client(self):
        if not config.WEIBO_EXTRACTION_ENABLED:
            return
        try:
            from aip import AipNlp
        except Exception as exc:
            utils.logger.warning("[store.weibo.extraction] import aip failed: %s", exc)
            return
        app_id = os.getenv("BAIDU_APP_ID", "").strip()
        api_key = os.getenv("BAIDU_API_KEY", "").strip()
        secret_key = os.getenv("BAIDU_SECRET_KEY", "").strip()
        if not (app_id and api_key and secret_key):
            utils.logger.warning(
                "[store.weibo.extraction] missing BAIDU_APP_ID/API_KEY/SECRET_KEY"
            )
            return
        self._extraction_client = AipNlp(app_id, api_key, secret_key)
        self._extraction_ready = True

    def _store_content_sync(self, content_item: dict):
        content_id = self._build_content_id(content_item.get("note_id"))
        if not content_id:
            return
        now = datetime.now()
        created_at = self._parse_datetime(content_item.get("create_date_time")) or now
        update_at = self._parse_datetime(now) or now
        content_text = self._clean_text(content_item.get("content", ""))
        if len(content_text) > self._MAX_TEXT_LENGTH:
            content_text = content_text[: self._MAX_TEXT_LENGTH]
        payload = {
            "content_id": content_id,
            "spider_id": self._spider_id(),
            "content_text": content_text,
            "reposts_count": str(content_item.get("shared_count", 0) or 0),
            "comments_count": str(content_item.get("comments_count", 0) or 0),
            "attitudes_count": str(content_item.get("liked_count", 0) or 0),
            "create_user": content_item.get("nickname", ""),
            "weibo_url": content_item.get("note_url", ""),
            "created_at": created_at,
            "update_at": update_at,
            "senti_score": int(content_item.get("senti_score", 0) or 0),
            "retweeted": int(content_item.get("retweeted", 0) or 0),
            "content_type": int(content_item.get("content_type", 2) or 2),
        }
        hotwords = self._extract_hotwords(payload["content_text"])
        inserted = True
        if self._session_factory:
            session = self._session_factory()
            inserted = False
            try:
                if self._content_mysql_enabled:
                    existing = session.get(WeiboContent, content_id)
                    if existing:
                        # Check if there are actual changes
                        has_changes = False
                        for key, value in payload.items():
                            if getattr(existing, key, None) != value:
                                has_changes = True
                                break

                        for key, value in payload.items():
                            setattr(existing, key, value)

                        if has_changes:
                            utils.logger.info(
                                f"[WeiboCompatStore] Updated content: {content_id} (有数据变化)"
                            )
                        else:
                            utils.logger.info(
                                f"[WeiboCompatStore] Updated content: {content_id} (无数据变化，仅刷新时间戳)"
                            )
                    else:
                        session.add(WeiboContent(**payload))
                        inserted = True
                        utils.logger.info(
                            f"[WeiboCompatStore] Inserted new content: {content_id} ✨"
                        )
                else:
                    inserted = True
                    utils.logger.info(
                        "[WeiboCompatStore] Skip content table write (MySQL disabled)"
                    )

                session.query(WeiboContentHotword).filter(
                    WeiboContentHotword.content_id == content_id
                ).delete(synchronize_session=False)
                if hotwords:
                    session.bulk_save_objects(
                        [
                            WeiboContentHotword(
                                content_id=content_id,
                                word=item["word"],
                                weight=item["weight"],
                            )
                            for item in hotwords
                        ]
                    )
                    utils.logger.debug(
                        f"[WeiboCompatStore] Saved {len(hotwords)} hotwords for {content_id}"
                    )
                session.commit()
                utils.logger.info(
                    f"[WeiboCompatStore] Successfully committed content: {content_id}"
                )
            except Exception as e:
                session.rollback()
                utils.logger.error(
                    f"[WeiboCompatStore] Failed to store content {content_id}: {e}"
                )
                raise
            finally:
                session.close()
            self._save_extraction(content_item, payload["content_text"])
        else:
            utils.logger.warning("[WeiboCompatStore] Session factory not initialized")

        self._incr_stat("content_inserted" if inserted else "content_updated")
        self._es_index(
            os.getenv("ES_INDEX_WEIBO", "weibocontent"),
            content_id,
            {
                "content_id": content_id,
                "spider_id": payload["spider_id"],
                "content_text": payload["content_text"],
                "reposts_count": int(payload["reposts_count"]),
                "comments_count": int(payload["comments_count"]),
                "attitudes_count": int(payload["attitudes_count"]),
                "create_user": payload["create_user"],
                "weibo_url": payload["weibo_url"],
                "created_at": payload["created_at"],
                "update_at": payload["update_at"],
                "senti_score": payload["senti_score"],
                "retweeted": payload["retweeted"],
                "content_type": payload["content_type"],
                "hotwords": hotwords,
            },
        )

    def _save_extraction(self, content_item: dict, content_text: str):
        if (
            not self._extraction_ready
            or not self._extraction_client
            or not self._session_factory
        ):
            return
        if not content_text:
            return
        text = self._extraction_html.sub("", content_text)
        if not text or text in config.WEIBO_EXTRACTION_INVALID:
            return
        content_id = self._build_content_id(content_item.get("note_id"))
        if not content_id:
            return
        session = self._session_factory()
        try:
            exists = (
                session.query(WebExtraction.id)
                .filter(WebExtraction.content_id == content_id)
                .first()
            )
            if exists:
                return
            options = {"type": config.WEIBO_EXTRACTION_TYPE}
            self._extraction_throttle()
            result = self._extraction_client.commentTag(text, options)
            if isinstance(result, dict) and result.get("error_code") in (17, 18):
                utils.logger.warning(
                    "[store.weibo.extraction] baidu limited: %s",
                    result.get("error_msg"),
                )
                return
            items = result.get("items") if isinstance(result, dict) else None
            if not items:
                return
            for item in items:
                abstract = item.get("abstract", "")
                if not abstract:
                    continue
                existing = (
                    session.query(WebExtraction.id)
                    .filter(
                        WebExtraction.content_id == content_id,
                        WebExtraction.abstract == abstract,
                    )
                    .first()
                )
                if existing:
                    continue
                prop = item.get("prop", "")
                adj = item.get("adj", "")
                if prop and not adj:
                    try:
                        lexer = self._extraction_client.lexer(prop)
                        for lex in lexer.get("items", []):
                            if (lex.get("pos") in config.WEIBO_EXTRACTION_NOUNS) or (
                                lex.get("ne") in config.WEIBO_EXTRACTION_NOUNS
                            ):
                                prop = lex.get("item", prop)
                            elif lex.get("pos") == "a":
                                adj = lex.get("item", adj)
                    except Exception as exc:
                        utils.logger.warning(
                            "[store.weibo.extraction] lexer failed: %s", exc
                        )
                session.add(
                    WebExtraction(
                        content_id=content_id,
                        prop=prop,
                        adj=adj,
                        abstract=abstract,
                        sentiment=item.get("sentiment"),
                    )
                )
            session.commit()
        except Exception as exc:
            session.rollback()
            utils.logger.warning("[store.weibo.extraction] save failed: %s", exc)
        finally:
            session.close()

    def _extraction_throttle(self):
        min_interval = max(0.0, float(config.WEIBO_EXTRACTION_MIN_INTERVAL_SEC))
        if min_interval <= 0:
            return
        with self._extraction_lock:
            now = time.time()
            sleep_for = min_interval - (now - self._extraction_last_ts)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._extraction_last_ts = time.time()

    def _store_comment_sync(self, comment_item: dict):
        note_id = comment_item.get("note_id")
        comment_id = comment_item.get("comment_id")
        content_id = self._build_content_id(note_id)
        if not content_id or not comment_id:
            return
        pinglun_id = f"{content_id}_{comment_id}"

        # 批量模式：添加到缓冲区
        if self._batch_enabled:
            # 缓存检查：跳过已处理的评论
            if self._comment_cache is not None:
                if pinglun_id in self._comment_cache:
                    utils.logger.debug(f"[WeiboCompatStore] Skip cached comment: {pinglun_id}")
                    return
                self._comment_cache.add(pinglun_id)

            with self._batch_lock:
                self._comment_buffer.append(comment_item)
                if len(self._comment_buffer) >= self._batch_size:
                    self._flush_comment_batch()
            return

        # 原有的单条写入逻辑（批量模式关闭时使用）
        now = datetime.now()
        created_at = self._parse_datetime(comment_item.get("create_date_time")) or now
        update_at = self._parse_datetime(now) or now
        comment_text = self._clean_text(comment_item.get("content", ""))
        if len(comment_text) > self._MAX_TEXT_LENGTH:
            comment_text = comment_text[: self._MAX_TEXT_LENGTH]
        payload = {
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
        hotwords = self._extract_hotwords(payload["pinglun_text"])
        inserted = True
        if self._session_factory:
            session = self._session_factory()
            inserted = False
            try:
                if self._comment_mysql_enabled:
                    existing = session.get(WeiboPinglun, pinglun_id)
                    if existing:
                        # Check if there are actual changes
                        has_changes = False
                        for key, value in payload.items():
                            if getattr(existing, key, None) != value:
                                has_changes = True
                                break

                        for key, value in payload.items():
                            setattr(existing, key, value)

                        if has_changes:
                            utils.logger.info(
                                f"[WeiboCompatStore] Updated comment: {pinglun_id} (有数据变化)"
                            )
                        else:
                            utils.logger.info(
                                f"[WeiboCompatStore] Updated comment: {pinglun_id} (无数据变化，仅刷新时间戳)"
                            )
                    else:
                        session.add(WeiboPinglun(**payload))
                        inserted = True
                        utils.logger.info(
                            f"[WeiboCompatStore] Inserted new comment: {pinglun_id} ✨"
                        )
                else:
                    inserted = True
                    utils.logger.info(
                        "[WeiboCompatStore] Skip comment table write (MySQL disabled)"
                    )

                session.query(WeiboPinglunHotword).filter(
                    WeiboPinglunHotword.pinglun_id == pinglun_id
                ).delete(synchronize_session=False)
                if hotwords:
                    session.bulk_save_objects(
                        [
                            WeiboPinglunHotword(
                                pinglun_id=pinglun_id,
                                word=item["word"],
                                weight=item["weight"],
                            )
                            for item in hotwords
                        ]
                    )
                    utils.logger.debug(
                        f"[WeiboCompatStore] Saved {len(hotwords)} hotwords for comment {pinglun_id}"
                    )
                session.commit()
                utils.logger.info(
                    f"[WeiboCompatStore] Successfully committed comment: {pinglun_id}"
                )
            except Exception as e:
                session.rollback()
                utils.logger.error(
                    f"[WeiboCompatStore] Failed to store comment {pinglun_id}: {e}"
                )
                raise
            finally:
                session.close()
        else:
            utils.logger.warning("[WeiboCompatStore] Session factory not initialized")

        self._incr_stat("comment_inserted" if inserted else "comment_updated")
        self._es_index(
            os.getenv("ES_INDEX_PINGLUN", "weibopinglun"),
            pinglun_id,
            {
                "pinglun_id": pinglun_id,
                "pinglun_parent_id": payload["pinglun_parent_id"],
                "pinglun_text": payload["pinglun_text"],
                "created_at": payload["created_at"],
                "update_at": payload["update_at"],
                "sub_pinglun_count": int(payload["sub_pinglun_count"]),
                "like_count": int(payload["like_count"]),
                "floor_number": int(payload["floor_number"]),
                "pinglun_user": payload["pinglun_user"],
                "weibo_content_id": payload["weibo_content_id"],
                "senti_score": payload["senti_score"],
                "hotwords": hotwords,
            },
        )

    def _build_content_id(self, note_id):
        if not note_id:
            return ""
        prefix = self._spider_id()
        return f"{prefix}_{note_id}" if prefix else str(note_id)

    def _spider_id(self):
        return source_keyword_var.get() or ""

    def _clean_text(self, text):
        if not text:
            return ""
        return self._html.sub("", text)

    def _normalize_datetime(self, value):
        if not value:
            return value
        if isinstance(value, datetime):
            # Remove timezone if present
            if value.tzinfo is not None:
                value = value.replace(tzinfo=None)
            return value.strftime("%Y-%m-%d %H:%M:%S")
        text = str(value).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}\d{2}:\d{2}:\d{2}", text):
            text = f"{text[:10]} {text[10:]}"
        text = text.replace("T", " ")
        tz_match = re.search(r"([+-]\d{2}:\d{2}|[+-]\d{4}|Z)$", text)
        if tz_match:
            text = text[: tz_match.start()]
        if len(text) > 19:
            text = text[:19]
        return text

    def _parse_datetime(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        text = self._normalize_datetime(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    def _load_stopwords(self):
        if self._stopwords is not None:
            return self._stopwords
        stopwords = set()
        path = config.STOP_WORDS_FILE
        if path and not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", path)
            path = os.path.abspath(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                stopwords = {line.strip() for line in fh if line.strip()}
        except Exception:
            stopwords = set()
        self._stopwords = stopwords
        return stopwords

    def _extract_hotwords(self, content):
        if not content:
            return []
        stopwords = self._load_stopwords()
        tokens = [self._non_word.sub("", t) for t in jieba.lcut(content, cut_all=False)]
        tokens = [t for t in tokens if t]
        token_counts = {}
        for token in tokens:
            normalized = token if self._contains_chinese(token) else token.lower()
            if self._is_stop_word(normalized, stopwords):
                continue
            if self._is_emoji(normalized):
                continue
            token_counts[normalized] = token_counts.get(normalized, 0) + 1
        results = [
            {"word": word, "weight": weight} for word, weight in token_counts.items()
        ]
        results.sort(key=lambda x: x["weight"], reverse=True)
        return [
            item for item in results if item["weight"] >= config.HOTWORDS_MIN_COUNT
        ][: config.HOTWORDS_TOP_N]

    def _is_stop_word(self, word, stopwords):
        if self._contains_chinese(word):
            if len(word.encode("utf-8")) < 6:
                return True
        else:
            if len(word) < 2:
                return True
        if word.lower() in stopwords:
            return True
        if word.isdigit():
            return True
        if not word.strip():
            return True
        return False

    def _contains_chinese(self, value):
        for ch in value:
            if "\u4e00" <= ch <= "\u9fff":
                return True
        return False

    def _is_emoji(self, value):
        for ch in value:
            if "\U0001f600" <= ch <= "\U0001f64f":
                return True
            if "\U0001f300" <= ch <= "\U0001f5ff":
                return True
            if "\U0001f680" <= ch <= "\U0001f6ff":
                return True
            if "\U0001f1e0" <= ch <= "\U0001f1ff":
                return True
            if "\ud000" <= ch <= "\udfff":
                return True
        return False

    def _ensure_index(self, index_name, mapping):
        if not self._es_enabled or not self._es_base or not index_name:
            return
        status, _ = self._http_request("HEAD", f"/{index_name}")
        if status == 200:
            return
        self._http_request("PUT", f"/{index_name}", mapping)

    def _es_index(self, index_name, doc_id, payload):
        if not self._es_enabled or not self._es_base or not index_name:
            return
        self._http_request("PUT", f"/{index_name}/_doc/{doc_id}", payload)

    def _json_default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return str(obj)

    def _http_request(self, method, path, body=None):
        safe_path = quote(path, safe="/%")
        url = f"{self._es_base}{safe_path}"
        data = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(
                body,
                ensure_ascii=False,
                default=self._json_default,
            ).encode("utf-8")
        req = urlrequest.Request(url, data=data, headers=headers, method=method)
        try:
            with urlrequest.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            body = e.read()
            utils.logger.warning(
                "[store.weibo.es] request failed status=%s url=%s body=%s",
                e.code,
                url,
                body[:200] if body else b"",
            )
            return e.code, body
        except (TimeoutError, socket.timeout, URLError) as exc:
            utils.logger.warning(
                "[store.weibo.es] request error url=%s error=%s", url, exc
            )
            return 0, b""

    # ========================================================================
    # 批量写入优化方法（ES Bulk API）
    # ========================================================================

    def _flush_comment_batch(self):
        """批量写入评论到 MySQL 和 ES"""
        if not self._comment_buffer:
            return

        comments = self._comment_buffer.copy()
        self._comment_buffer.clear()

        utils.logger.info(f"[WeiboCompatStore] Flushing {len(comments)} comments (batch mode)...")

        # 处理每条评论的数据
        mysql_payloads = []
        es_payloads = []
        hotword_deletions = []
        hotword_insertions = []

        for comment_item in comments:
            note_id = comment_item.get("note_id")
            comment_id = comment_item.get("comment_id")
            content_id = self._build_content_id(note_id)
            if not content_id or not comment_id:
                continue

            pinglun_id = f"{content_id}_{comment_id}"
            now = datetime.now()
            created_at = self._parse_datetime(comment_item.get("create_date_time")) or now
            update_at = self._parse_datetime(now) or now
            comment_text = self._clean_text(comment_item.get("content", ""))
            if len(comment_text) > self._MAX_TEXT_LENGTH:
                comment_text = comment_text[: self._MAX_TEXT_LENGTH]

            payload = {
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

            # 提取热词
            hotwords = self._extract_hotwords(payload["pinglun_text"])

            # 收集 MySQL 数据
            mysql_payloads.append((pinglun_id, payload, hotwords))

            # 收集 ES 数据
            es_payloads.append({
                "pinglun_id": pinglun_id,
                "pinglun_parent_id": payload["pinglun_parent_id"],
                "pinglun_text": payload["pinglun_text"],
                "created_at": payload["created_at"],
                "update_at": payload["update_at"],
                "sub_pinglun_count": payload["sub_pinglun_count"],
                "like_count": payload["like_count"],
                "floor_number": payload["floor_number"],
                "pinglun_user": payload["pinglun_user"],
                "weibo_content_id": content_id,
                "senti_score": payload["senti_score"],
            })

            hotword_deletions.append(pinglun_id)
            if hotwords:
                for hw in hotwords:
                    hotword_insertions.append({
                        "pinglun_id": pinglun_id,
                        "word": hw["word"],
                        "weight": hw["weight"],
                    })

        # 1. 批量写入 MySQL（如果启用）
        if self._session_factory and self._comment_mysql_enabled:
            session = self._session_factory()
            try:
                # 删除旧热词（批量）
                if hotword_deletions:
                    from sqlalchemy import delete
                    stmt = delete(WeiboPinglunHotword).where(
                        WeiboPinglunHotword.pinglun_id.in_(hotword_deletions)
                    )
                    session.execute(stmt)

                # 批量插入/更新评论
                for pinglun_id, payload, hotwords in mysql_payloads:
                    existing = session.get(WeiboPinglun, pinglun_id)
                    if existing:
                        for key, value in payload.items():
                            setattr(existing, key, value)
                    else:
                        session.add(WeiboPinglun(**payload))

                # 批量插入热词
                if hotword_insertions:
                    session.bulk_insert_mappings(WeiboPinglunHotword, hotword_insertions)

                session.commit()
                utils.logger.info(f"[WeiboCompatStore] MySQL: Committed {len(mysql_payloads)} comments with hotwords")
            except Exception as e:
                session.rollback()
                utils.logger.error(f"[WeiboCompatStore] MySQL batch failed: {e}")
            finally:
                session.close()

        # 2. 批量写入 ES（使用 Bulk API）
        if self._es_enabled and es_payloads:
            self._es_bulk_index(os.getenv("ES_INDEX_PINGLUN", "weibopinglun"), es_payloads)

        utils.logger.info(f"[WeiboCompatStore] Batch flush completed: {len(comments)} comments")

    def _es_bulk_index(self, index_name, docs):
        """使用 ES Bulk API 批量索引文档"""
        if not self._es_base or not docs:
            return

        # 构建 Bulk API 请求体（NDJSON 格式）
        bulk_lines = []
        for doc in docs:
            doc_id = doc.get("pinglun_id")
            if not doc_id:
                continue

            # Action 行
            action = {"index": {"_index": index_name, "_id": doc_id}}
            bulk_lines.append(json.dumps(action, ensure_ascii=False))

            # Document 行
            bulk_lines.append(json.dumps(doc, ensure_ascii=False, default=self._json_default))

        if not bulk_lines:
            return

        # 拼接为 NDJSON（每行一个 JSON，结尾必须有换行符）
        bulk_body = "\n".join(bulk_lines) + "\n"

        # 调用 Bulk API
        url = f"{self._es_base}/_bulk"
        headers = {
            "Content-Type": "application/x-ndjson",
            "Accept": "application/json"
        }
        req = urlrequest.Request(
            url,
            data=bulk_body.encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                result_data = resp.read()
                result = json.loads(result_data)

                if result.get("errors"):
                    # 有错误，记录详细信息
                    error_items = [item for item in result.get("items", [])
                                  if item.get("index", {}).get("error")]
                    error_count = len(error_items)
                    utils.logger.warning(
                        f"[WeiboCompatStore] ES Bulk: {error_count} errors out of {len(docs)} docs"
                    )
                    # 记录第一个错误示例
                    if error_items:
                        first_error = error_items[0].get("index", {}).get("error")
                        utils.logger.warning(f"[WeiboCompatStore] ES Bulk error example: {first_error}")
                else:
                    utils.logger.info(f"[WeiboCompatStore] ES Bulk: Successfully indexed {len(docs)} documents")

        except HTTPError as e:
            body = e.read()
            utils.logger.error(
                f"[WeiboCompatStore] ES Bulk failed: status={e.code}, body={body[:500]}"
            )
        except (TimeoutError, socket.timeout, URLError) as exc:
            utils.logger.error(f"[WeiboCompatStore] ES Bulk request error: {exc}")

    async def flush_all(self):
        """刷新所有批量缓冲区（程序结束前调用）"""
        if self._batch_enabled:
            await asyncio.to_thread(self._flush_all_sync)

    def _flush_all_sync(self):
        """同步刷新所有缓冲区"""
        with self._batch_lock:
            if self._comment_buffer:
                utils.logger.info(f"[WeiboCompatStore] Flushing remaining {len(self._comment_buffer)} comments...")
                self._flush_comment_batch()

            if self._content_buffer:
                utils.logger.info(f"[WeiboCompatStore] Flushing remaining {len(self._content_buffer)} contents...")
                # TODO: 实现内容批量刷新

        utils.logger.info("[WeiboCompatStore] All batch buffers flushed")
