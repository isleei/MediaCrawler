# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/services/weibo_storage.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

import redis
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, desc
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base, WebUITask, WebUICookie, WebUICookieBundle,
    WebUIProxy, WebUISentimentWord, WebUIConfig,
    WebUITaskLog, WebUITaskData, WebUIBatch
)
from database.db_utils import create_mysql_engine_safe

# 加载 .env 文件
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class WeiboStorage:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )

        _mysql_enabled = os.getenv("MONITOR_MYSQL_ENABLED")
        self.mysql_enabled = True if _mysql_enabled is None else _mysql_enabled in ("1", "true", "True")

        self.engine = None
        self.SessionLocal = None

        # 情感词典缓存
        self._sentiment_cache = {}
        self._sentiment_cache_ts = {}
        self._sentiment_cache_ttl = int(os.getenv("SENTI_CACHE_TTL", "60"))

        if self.mysql_enabled:
            host = os.getenv("MONITOR_MYSQL_HOST", os.getenv("MYSQL_DB_HOST", "127.0.0.1"))
            port = int(os.getenv("MONITOR_MYSQL_PORT", os.getenv("MYSQL_DB_PORT", "3306")))
            dbname = os.getenv("MONITOR_MYSQL_DBNAME", os.getenv("MYSQL_DB_NAME", "yuqing"))
            user = os.getenv("MONITOR_MYSQL_USER", os.getenv("MYSQL_DB_USER", "root"))
            password = os.getenv("MONITOR_MYSQL_PASSWORD", os.getenv("MYSQL_DB_PWD", ""))
            charset = os.getenv("MONITOR_MYSQL_CHARSET", os.getenv("MYSQL_CHARSET", "utf8mb4"))

            self.engine = create_mysql_engine_safe(
                host=host, port=port, user=user, password=password, database=dbname, charset=charset,
            )
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def _get_db(self) -> Session:
        if not self.SessionLocal: raise Exception("MySQL not configured")
        return self.SessionLocal()

    # Task Operations
    def save_task(self, data: Dict[str, Any]):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            task = WebUITask(
                task_id=str(data["id"]), keyword=data.get("keyword"), max_pages=int(data.get("max_pages", 0)),
                with_comments=int(data.get("with_comments", 0)), status=data.get("status"),
                created_at=data.get("created_at"), started_at=data.get("started_at"),
                finished_at=data.get("finished_at"), items_count=int(data.get("items_count", 0)),
                pid=str(data.get("pid", "")), output_file=data.get("output_file"),
                data_key=data.get("data_key"), task_type='weibo',
                pages_crawled=int(data.get("pages_crawled", 0)),
                content_inserted=int(data.get("content_inserted", 0)),
                content_updated=int(data.get("content_updated", 0)),
                comment_inserted=int(data.get("comment_inserted", 0)),
                comment_updated=int(data.get("comment_updated", 0))
            )
            db.merge(task); db.commit()
        finally: db.close()

    def update_task(self, task_id: Any, mapping: Dict[str, Any]):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            task = db.query(WebUITask).filter(WebUITask.task_id == str(task_id)).first()
            if task:
                for k, v in mapping.items():
                    if hasattr(task, k): setattr(task, k, v)
                db.commit()
        finally: db.close()

    def get_task(self, task_id: Any) -> Optional[Dict[str, Any]]:
        if not self.mysql_enabled: return None
        db = self._get_db()
        try:
            t = db.query(WebUITask).filter(WebUITask.task_id == str(task_id)).first()
            return {
                "id": int(t.task_id), "keyword": t.keyword, "max_pages": t.max_pages,
                "with_comments": t.with_comments, "status": t.status, "created_at": t.created_at,
                "started_at": t.started_at, "finished_at": t.finished_at, "items_count": t.items_count,
                "pid": t.pid, "output_file": t.output_file, "data_key": t.data_key,
                "pages_crawled": t.pages_crawled, "content_inserted": t.content_inserted
            } if t else None
        finally: db.close()

    def list_tasks(self) -> List[Dict[str, Any]]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            tasks = db.query(WebUITask).filter(WebUITask.task_type == 'weibo').order_by(desc(WebUITask.id)).all()
            return [{
                "id": int(t.task_id), "keyword": t.keyword, "max_pages": t.max_pages,
                "with_comments": t.with_comments, "status": t.status, "created_at": t.created_at,
                "started_at": t.started_at, "finished_at": t.finished_at,
                "items_count": t.items_count, "pid": t.pid
            } for t in tasks]
        finally: db.close()

    def delete_task(self, task_id: Any):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            db.query(WebUITask).filter(WebUITask.task_id == str(task_id)).delete()
            db.query(WebUITaskLog).filter(WebUITaskLog.task_id == str(task_id)).delete()
            db.query(WebUITaskData).filter(WebUITaskData.task_id == str(task_id)).delete()
            db.commit()
        finally: db.close()

    # Cookie Operations
    def save_cookie(self, name: str, payload: Dict[str, Any]):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            cookie = WebUICookie(
                name=name, value=json.dumps(payload, ensure_ascii=False),
                enabled=int(payload.get("enabled", 1)), status=payload.get("status", "unknown"),
                cookie_type='weibo'
            )
            db.merge(cookie); db.commit()
        finally: db.close()

    def list_cookies(self) -> List[Dict[str, Any]]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            cookies = db.query(WebUICookie).filter(WebUICookie.cookie_type == 'weibo').all()
            return [json.loads(c.value) for c in cookies]
        finally: db.close()

    def delete_cookie(self, name: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            db.query(WebUICookie).filter(WebUICookie.name == name).delete()
            db.commit()
        finally: db.close()

    def get_cookie(self, name: str) -> Optional[Dict[str, Any]]:
        if not self.mysql_enabled: return None
        db = self._get_db()
        try:
            c = db.query(WebUICookie).filter(WebUICookie.name == name).first()
            return json.loads(c.value) if c else None
        finally: db.close()

    # Cookie Bundle Operations
    def save_cookie_bundle(self, name: str, cookie_string: str, proxies: Any, user_agent: str = ""):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            proxy_list = proxies if isinstance(proxies, list) else []
            bundle = WebUICookieBundle(
                name=name, cookie_string=cookie_string, proxies=json.dumps(proxy_list, ensure_ascii=False),
                user_agent=user_agent, updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                enabled=1, status='unknown', bundle_type='weibo'
            )
            db.merge(bundle); db.commit()
        finally: db.close()

    def get_cookie_bundle(self, name: str) -> Optional[Dict[str, Any]]:
        if not self.mysql_enabled: return None
        db = self._get_db()
        try:
            b = db.query(WebUICookieBundle).filter(WebUICookieBundle.name == name).first()
            return {
                "name": b.name, "cookie_string": b.cookie_string, "proxies": b.proxies,
                "user_agent": b.user_agent, "updated_at": b.updated_at, "enabled": str(b.enabled), "status": b.status
            } if b else None
        finally: db.close()

    def list_cookie_bundles(self) -> List[Dict[str, Any]]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            bundles = db.query(WebUICookieBundle).filter(WebUICookieBundle.bundle_type == 'weibo').all()
            return [{
                "name": b.name, "cookie_string": b.cookie_string, "enabled": str(b.enabled), "status": b.status
            } for b in bundles]
        finally: db.close()

    def delete_cookie_bundle(self, name: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            db.query(WebUICookieBundle).filter(WebUICookieBundle.name == name).delete()
            db.commit()
        finally: db.close()

    def update_cookie_bundle_status(self, name: str, enabled: bool, status: str, remark: str = ""):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            bundle = db.query(WebUICookieBundle).filter(WebUICookieBundle.name == name).first()
            if bundle:
                bundle.enabled = 1 if enabled else 0; bundle.status = status; db.commit()
        finally: db.close()

    # Proxy Operations
    def list_proxies(self) -> List[str]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            proxies = db.query(WebUIProxy).filter(WebUIProxy.proxy_type == 'weibo').all()
            return [p.proxy for p in proxies]
        finally: db.close()

    def add_proxy(self, proxy: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            p = WebUIProxy(proxy=proxy, proxy_type='weibo')
            db.merge(p); db.commit()
        finally: db.close()

    def delete_proxy(self, proxy: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            db.query(WebUIProxy).filter(WebUIProxy.proxy == proxy).delete(); db.commit()
        finally: db.close()

    # Sentiment Word Operations
    def list_sentiment_words(self, word_type: str) -> List[str]:
        """获取情感词典，带缓存"""
        if not self.mysql_enabled:
            return []

        # 检查缓存
        import time
        now = time.time()
        if word_type in self._sentiment_cache:
            if (now - self._sentiment_cache_ts.get(word_type, 0)) < self._sentiment_cache_ttl:
                return self._sentiment_cache[word_type]

        # 从数据库读取
        db = self._get_db()
        try:
            words = db.query(WebUISentimentWord).filter(
                WebUISentimentWord.word_type == word_type,
                WebUISentimentWord.platform == 'weibo'
            ).all()
            result = sorted([w.word for w in words])

            # 更新缓存
            self._sentiment_cache[word_type] = result
            self._sentiment_cache_ts[word_type] = now

            return result
        finally:
            db.close()

    def _clear_sentiment_cache(self, word_type: str = None):
        """清除情感词典缓存"""
        if word_type:
            self._sentiment_cache.pop(word_type, None)
            self._sentiment_cache_ts.pop(word_type, None)
        else:
            self._sentiment_cache.clear()
            self._sentiment_cache_ts.clear()

    def _sync_sentiment_to_redis(self, word_type: str):
        """同步情感词典到 Redis"""
        try:
            redis_key = f"weibo:senti:{word_type}"
            words = self.list_sentiment_words(word_type)

            # 清空 Redis 中的旧数据
            self.redis_client.delete(redis_key)

            # 批量添加新数据（每批1000个）
            if words:
                batch_size = 1000
                for i in range(0, len(words), batch_size):
                    batch = words[i:i+batch_size]
                    self.redis_client.sadd(redis_key, *batch)
        except Exception as e:
            print(f"同步情感词典到 Redis 失败: {e}")

    def sync_all_sentiment_to_redis(self):
        """同步所有情感词典到 Redis"""
        sentiment_types = ["positive", "negative", "negation", "degree", "stopwords"]
        for word_type in sentiment_types:
            self._sync_sentiment_to_redis(word_type)
        print("✓ 所有情感词典已同步到 Redis")

    def add_sentiment_word(self, word_type: str, word: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            # 检查是否已存在
            existing = db.query(WebUISentimentWord).filter(
                WebUISentimentWord.word_type == word_type,
                WebUISentimentWord.word == word,
                WebUISentimentWord.platform == 'weibo'
            ).first()
            if not existing:
                w = WebUISentimentWord(word_type=word_type, word=word, platform='weibo')
                db.add(w)
                db.commit()

                # 清除缓存并同步到 Redis
                self._clear_sentiment_cache(word_type)
                self._sync_sentiment_to_redis(word_type)
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def remove_sentiment_word(self, word_type: str, word: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            db.query(WebUISentimentWord).filter(
                WebUISentimentWord.word_type == word_type,
                WebUISentimentWord.word == word,
                WebUISentimentWord.platform == 'weibo'
            ).delete()
            db.commit()

            # 清除缓存并同步到 Redis
            self._clear_sentiment_cache(word_type)
            self._sync_sentiment_to_redis(word_type)
        finally:
            db.close()

    # Config Operations
    def save_config(self, key: str, value: Dict[str, Any]):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            # 先查询是否存在
            existing = db.query(WebUIConfig).filter(WebUIConfig.config_key == key).first()
            if existing:
                # 更新现有配置
                existing.config_value = json.dumps(value, ensure_ascii=False)
                existing.config_type = 'weibo'
            else:
                # 插入新配置
                cfg = WebUIConfig(config_key=key, config_value=json.dumps(value, ensure_ascii=False), config_type='weibo')
                db.add(cfg)
            db.commit()
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def get_config(self, key: str) -> Dict[str, Any]:
        if not self.mysql_enabled: return {}
        db = self._get_db()
        try:
            cfg = db.query(WebUIConfig).filter(WebUIConfig.config_key == key).first()
            return json.loads(cfg.config_value) if cfg else {}
        finally: db.close()

    # Logs & Data
    def append_log(self, task_id: Any, line: str):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            # 移除或替换 4 字节 UTF-8 字符（emoji）
            import re
            # 移除 emoji 和其他 4 字节字符
            line = re.sub(r'[\U00010000-\U0010ffff]', '', line)
            log = WebUITaskLog(task_id=str(task_id), content=line)
            db.add(log); db.commit()
        except Exception as e:
            db.rollback()
        finally: db.close()

    def get_logs(self, task_id: Any, limit: int = 200) -> List[str]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            logs = db.query(WebUITaskLog).filter(WebUITaskLog.task_id == str(task_id)).order_by(desc(WebUITaskLog.id)).limit(limit).all()
            return [l.content for l in reversed(logs)]
        finally: db.close()

    def append_data(self, task_id: Any, data: Dict[str, Any], data_type: str = 'item'):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            item = WebUITaskData(task_id=str(task_id), content=json.dumps(data, ensure_ascii=False), data_type=data_type)
            db.add(item); db.commit()
        finally: db.close()

    # Batch Operations
    def save_batch(self, data: Dict[str, Any]):
        if not self.mysql_enabled: return
        db = self._get_db()
        try:
            batch = WebUIBatch(
                batch_id=str(data["batch_id"]), name=data.get("name", ""), status=data.get("status", "pending"),
                created_at=data.get("created_at"), task_ids=json.dumps(data.get("task_ids", [])),
                template_count=int(data.get("template_count", 0)), completed_count=int(data.get("completed_count", 0)),
                failed_count=int(data.get("failed_count", 0)), batch_type='weibo'
            )
            db.merge(batch); db.commit()
        finally: db.close()

    def list_batches(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.mysql_enabled: return []
        db = self._get_db()
        try:
            batches = db.query(WebUIBatch).filter(WebUIBatch.batch_type == 'weibo').order_by(desc(WebUIBatch.id)).limit(limit).all()
            return [{
                "batch_id": int(b.batch_id), "name": b.name, "status": b.status, "created_at": b.created_at
            } for b in batches]
        finally: db.close()

    def append_batch_log(self, batch_id: Any, message: str):
        self.append_log(f"batch_{batch_id}", message)

    # Utils
    def get_next_id(self, key: str) -> int:
        if self.mysql_enabled:
            db = self._get_db()
            try:
                if "task" in key: sql = "SELECT MAX(CAST(task_id AS SIGNED)) FROM web_ui_tasks"
                elif "batch" in key: sql = "SELECT MAX(CAST(batch_id AS SIGNED)) FROM web_ui_batches"
                else: return self.redis_client.incr(key)
                res = db.execute(text(sql)).scalar()
                return (int(res) if res else 0) + 1
            finally: db.close()
        return self.redis_client.incr(key)

    def migrate_from_redis(self):
        """全面迁移 Redis 数据到 MySQL"""
        if not self.mysql_enabled:
            print("MySQL not enabled, skipping migration")
            return

        print("=" * 60)
        print("开始从 Redis 迁移数据到 MySQL")
        print("=" * 60)

        # 1. 迁移任务
        print("\n[1/7] 迁移任务 (Tasks)...")
        try:
            tids = self.redis_client.lrange("weibo:tasks", 0, -1)
            print(f"  找到 {len(tids)} 个任务")
            success_count = 0
            for tid in tids:
                try:
                    d = self.redis_client.hgetall(f"weibo:task:{tid}")
                    if d:
                        self.save_task({"id": tid, **d})
                        # 迁移任务日志（只迁移不存在的日志）
                        logs = self.redis_client.lrange(f"weibo:task:logs:{tid}", 0, -1)
                        for l in logs:
                            self.append_log(tid, l)
                        success_count += 1
                except Exception as e:
                    # 跳过已存在的任务
                    if "Duplicate entry" not in str(e):
                        print(f"  警告: 任务 {tid} 迁移失败: {e}")
            print(f"  ✓ 成功迁移 {success_count}/{len(tids)} 个任务")
        except Exception as e:
            print(f"  ✗ 任务迁移失败: {e}")

        # 2. 迁移 Cookies
        print("\n[2/7] 迁移 Cookies...")
        try:
            cookie_names = self.redis_client.lrange("weibo:cookies", 0, -1)
            print(f"  找到 {len(cookie_names)} 个 cookie")
            success_count = 0
            for name in cookie_names:
                try:
                    d = self.redis_client.hgetall(f"weibo:cookie:{name}")
                    if d:
                        self.save_cookie(name, d)
                        success_count += 1
                except Exception as e:
                    if "Duplicate entry" not in str(e):
                        print(f"  警告: Cookie {name} 迁移失败: {e}")
            print(f"  ✓ 成功迁移 {success_count}/{len(cookie_names)} 个 cookie")
        except Exception as e:
            print(f"  ✗ Cookie 迁移失败: {e}")

        # 3. 迁移 Cookie Bundles
        print("\n[3/7] 迁移 Cookie Bundles...")
        try:
            # 扫描所有 cookie bundle keys
            bundle_keys = []
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor, match="weibo:cookie:bundle:*", count=100)
                bundle_keys.extend(keys)
                if cursor == 0:
                    break

            print(f"  找到 {len(bundle_keys)} 个 cookie bundle")
            success_count = 0
            for key in bundle_keys:
                try:
                    name = key.replace("weibo:cookie:bundle:", "")
                    d = self.redis_client.hgetall(key)
                    if d:
                        cookie_string = d.get("cookie_string", "")
                        proxies_str = d.get("proxies", "")
                        try:
                            proxies = json.loads(proxies_str) if proxies_str else []
                        except:
                            proxies = []
                        user_agent = d.get("user_agent", "")
                        self.save_cookie_bundle(name, cookie_string, proxies, user_agent)

                        # 更新状态
                        enabled = d.get("enabled", "1") in ("1", "true", "True")
                        status = d.get("status", "unknown")
                        self.update_cookie_bundle_status(name, enabled, status)
                        success_count += 1
                except Exception as e:
                    if "Duplicate entry" not in str(e):
                        print(f"  警告: Cookie Bundle {name} 迁移失败: {e}")
            print(f"  ✓ 成功迁移 {success_count}/{len(bundle_keys)} 个 cookie bundle")
        except Exception as e:
            print(f"  ✗ Cookie Bundle 迁移失败: {e}")

        # 4. 迁移 Proxies
        print("\n[4/7] 迁移 Proxies...")
        try:
            # 尝试从 set 或 list 中获取
            proxies = []
            try:
                proxies = list(self.redis_client.smembers("weibo:proxies"))
            except:
                proxies = self.redis_client.lrange("weibo:proxies", 0, -1)

            print(f"  找到 {len(proxies)} 个代理")
            for proxy in proxies:
                if proxy:
                    self.add_proxy(proxy)
            print(f"  ✓ 成功迁移 {len(proxies)} 个代理")
        except Exception as e:
            print(f"  ✗ Proxy 迁移失败: {e}")

        # 5. 迁移情感词典
        print("\n[5/7] 迁移情感词典 (Sentiment Words)...")
        try:
            sentiment_types = ["positive", "negative", "negation", "degree", "stopwords"]
            total_words = 0
            success_count = 0

            db = self._get_db()
            try:
                for word_type in sentiment_types:
                    key = f"weibo:senti:{word_type}"
                    words = list(self.redis_client.smembers(key))
                    print(f"  - {word_type}: {len(words)} 个词", end="", flush=True)

                    # 批量插入
                    type_success = 0
                    batch_size = 500
                    for i in range(0, len(words), batch_size):
                        batch = words[i:i+batch_size]
                        for word in batch:
                            if word:
                                try:
                                    # 检查是否已存在
                                    existing = db.query(WebUISentimentWord).filter(
                                        WebUISentimentWord.word_type == word_type,
                                        WebUISentimentWord.word == word,
                                        WebUISentimentWord.platform == 'weibo'
                                    ).first()
                                    if not existing:
                                        w = WebUISentimentWord(word_type=word_type, word=word, platform='weibo')
                                        db.add(w)
                                        type_success += 1
                                except Exception as e:
                                    pass  # 静默跳过错误
                        # 每批次提交一次
                        try:
                            db.commit()
                        except Exception as e:
                            db.rollback()

                    total_words += len(words)
                    success_count += type_success
                    print(f" (新增 {type_success} 个)")
            finally:
                db.close()

            print(f"  ✓ 成功迁移 {success_count}/{total_words} 个情感词")
        except Exception as e:
            print(f"  ✗ 情感词典迁移失败: {e}")

        # 6. 迁移配置
        print("\n[6/7] 迁移配置 (Configs)...")
        try:
            config_keys = ["weibo:webhook:config", "weibo:schedule:config"]
            migrated_count = 0
            for key in config_keys:
                config_data = self.redis_client.hgetall(key)
                if config_data:
                    self.save_config(key, config_data)
                    migrated_count += 1
                    print(f"  - {key}: ✓")
            print(f"  ✓ 成功迁移 {migrated_count} 个配置")
        except Exception as e:
            print(f"  ✗ 配置迁移失败: {e}")

        # 7. 迁移批次
        print("\n[7/7] 迁移批次 (Batches)...")
        try:
            bids = self.redis_client.lrange("weibo:batches", 0, -1)
            print(f"  找到 {len(bids)} 个批次")
            success_count = 0
            for bid in bids:
                try:
                    d = self.redis_client.hgetall(f"weibo:batch:{bid}")
                    if d:
                        try:
                            d['task_ids'] = json.loads(d.get('task_ids', '[]'))
                        except:
                            d['task_ids'] = []
                        self.save_batch({"batch_id": bid, **d})

                        # 迁移批次日志
                        logs = self.redis_client.lrange(f"weibo:batch:logs:{bid}", 0, -1)
                        for l in logs:
                            self.append_batch_log(bid, l)
                        success_count += 1
                except Exception as e:
                    if "Duplicate entry" not in str(e):
                        print(f"  警告: 批次 {bid} 迁移失败: {e}")
            print(f"  ✓ 成功迁移 {success_count}/{len(bids)} 个批次")
        except Exception as e:
            print(f"  ✗ 批次迁移失败: {e}")

        print("\n" + "=" * 60)
        print("迁移完成！")
        print("=" * 60)

weibo_storage = WeiboStorage()
