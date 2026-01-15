# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/weibo_ui.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import json
import logging
import os
import re
import shlex
import signal
import subprocess
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import redis
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from ..services.weibo_storage import weibo_storage

load_dotenv()

router = APIRouter(prefix="/weibo/api", tags=["weibo-ui"])

DATA_DIR = "data"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "web.log")
TASK_LOG_DIR = os.path.join(LOG_DIR, "tasks")

app_logger = logging.getLogger("weibo-ui")
app_logger.setLevel(logging.INFO)
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    app_logger.addHandler(handler)
except PermissionError:
    app_logger.warning("日志目录不可写，跳过文件日志配置")

# Configs
DEFAULT_COOKIE_BUNDLE_NAME = os.getenv("WEIBO_COOKIE_BUNDLE_NAME", "")
MONITOR_COOKIE_BUNDLE_NAME = os.getenv("MONITOR_COOKIE_BUNDLE_NAME", "")
TASK_ID_KEY = "weibo:task:id"
BATCH_ID_KEY = "weibo:batch:id"
TASK_SPIDER_AUTOSTART = os.getenv("MONITOR_SPIDER_AUTOSTART", "1") not in ("0", "false", "False")
TASK_SPIDER_CMD = os.getenv("MONITOR_TASK_SPIDER_CMD", "uv run python main.py --platform wb --type search")
TASK_SPIDER_LOCK_PREFIX = "weibo:task:running:"
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_MAX_PAGES", "5"))
WEIBO_PAGE_SIZE = int(os.getenv("WEIBO_PAGE_SIZE", "10"))
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "1"))  # 最大并发任务数
ENABLE_COOKIE_RETRY = os.getenv("ENABLE_COOKIE_RETRY", "1") not in ("0", "false", "False")  # 启用 Cookie 重试
MAX_COOKIE_RETRY = int(os.getenv("MAX_COOKIE_RETRY", "2"))  # Cookie 失败后最大重试次数

# Using weibo_storage's engine if available
monitor_engine = weibo_storage.engine

# 任务队列管理
task_queue_lock = threading.Lock()
running_task_cookies = {}  # {task_id: cookie_bundle_name}
task_cookie_history = {}  # {task_id: [cookie1, cookie2, ...]} 记录任务使用过的 Cookie
task_retry_count = {}  # {task_id: retry_count} 记录任务重试次数

def init_task_queue():
    """初始化任务队列，恢复运行中的任务状态"""
    app_logger.info("Initializing task queue...")

    tasks = weibo_storage.list_tasks()
    recovered_count = 0
    cleaned_count = 0

    for task in tasks:
        if task.get("status") == "running":
            task_id = task.get("id")
            pid = task.get("pid")
            cookie_name = task.get("data_key")  # 从任务中读取使用的 cookie

            # 检查进程是否还在运行
            if _is_process_alive(pid):
                # 恢复 cookie 分配
                if cookie_name:
                    with task_queue_lock:
                        running_task_cookies[task_id] = cookie_name
                    app_logger.info(f"Recovered task {task_id} with cookie {cookie_name}")
                    recovered_count += 1
                else:
                    app_logger.warning(f"Task {task_id} is running but has no cookie assigned")
            else:
                # 进程已死，清理状态
                update_task(task_id, {
                    "status": "stopped",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "pid": ""
                })
                append_task_log(task_id, "服务器重启后检测到进程已停止")
                app_logger.info(f"Cleaned up dead task {task_id}")
                cleaned_count += 1

    app_logger.info(f"Task queue initialized: {recovered_count} recovered, {cleaned_count} cleaned")

    # 处理队列中的任务
    try:
        process_queued_tasks()
    except Exception as e:
        app_logger.error(f"Error processing queued tasks on init: {e}")

def get_available_cookie_bundle(exclude_cookies=None):
    """获取可用的 cookie bundle（未被其他任务使用）

    Args:
        exclude_cookies: 要排除的 cookie 列表（例如任务已经尝试过的 cookie）
    """
    bundles = list_cookie_bundles()
    if not bundles:
        return None

    # 过滤出启用的 bundle
    enabled_bundles = [b for b in bundles if b.get("enabled", "1") not in ("0", "false", "False")]
    if not enabled_bundles:
        return None

    # 找出未被使用的 bundle
    used_bundles = set(running_task_cookies.values())
    available_bundles = [b for b in enabled_bundles if b.get("name") not in used_bundles]

    # 排除已经尝试过的 cookie
    if exclude_cookies:
        available_bundles = [b for b in available_bundles if b.get("name") not in exclude_cookies]

    if not available_bundles:
        return None

    # 优先选择状态为 ok 的 bundle
    healthy_bundles = [b for b in available_bundles if b.get("status") == "ok"]
    if healthy_bundles:
        return healthy_bundles[0].get("name")

    # 如果没有健康的，返回第一个可用的
    return available_bundles[0].get("name")

def get_running_tasks_count():
    """获取当前运行中的任务数量"""
    with task_queue_lock:
        return len(running_task_cookies)

def can_start_new_task():
    """检查是否可以启动新任务"""
    return get_running_tasks_count() < MAX_CONCURRENT_TASKS

def allocate_cookie_for_task(task_id):
    """为任务分配 cookie"""
    with task_queue_lock:
        # 获取任务已经尝试过的 cookie
        tried_cookies = task_cookie_history.get(task_id, [])
        cookie_bundle = get_available_cookie_bundle(exclude_cookies=tried_cookies)

        if cookie_bundle:
            running_task_cookies[task_id] = cookie_bundle
            # 记录使用历史
            if task_id not in task_cookie_history:
                task_cookie_history[task_id] = []
            task_cookie_history[task_id].append(cookie_bundle)

        return cookie_bundle

def release_cookie_for_task(task_id):
    """释放任务的 cookie"""
    with task_queue_lock:
        if task_id in running_task_cookies:
            del running_task_cookies[task_id]

def clear_task_history(task_id):
    """清除任务的历史记录（任务完成或最终失败时调用）"""
    with task_queue_lock:
        task_cookie_history.pop(task_id, None)
        task_retry_count.pop(task_id, None)

def should_retry_with_new_cookie(task_id, return_code):
    """判断是否应该使用新 Cookie 重试

    Args:
        task_id: 任务 ID
        return_code: 进程返回码

    Returns:
        bool: 是否应该重试
    """
    if not ENABLE_COOKIE_RETRY:
        return False

    # 获取重试次数
    retry_count = task_retry_count.get(task_id, 0)
    if retry_count >= MAX_COOKIE_RETRY:
        app_logger.info(f"Task {task_id} reached max retry limit ({MAX_COOKIE_RETRY})")
        return False

    # 只有微博接口相关错误才触发 Cookie 重试/禁用
    if return_code != 0:
        logs = _read_task_log_lines(task_id, limit=200)
        if not logs:
            return False
        error_markers = (
            "[WeiboClient.request] request",
            "[WeiboClient.pong] cookie may be invalid",
            "[WeiboClient.pong] Pong weibo failed",
            "get response code error:",
            "err code: 403",
            "err code: 418",
            "err code: 429",
            "err code: 432",
        )
        for line in logs:
            if any(marker in line for marker in error_markers):
                return True
        return False

    return False

def retry_task_with_new_cookie(task_id, keyword, max_pages):
    """使用新的 Cookie 重试任务"""
    with task_queue_lock:
        retry_count = task_retry_count.get(task_id, 0)
        task_retry_count[task_id] = retry_count + 1

    # 分配新的 Cookie（排除已尝试过的）
    cookie_bundle = allocate_cookie_for_task(task_id)

    if cookie_bundle:
        tried_cookies = task_cookie_history.get(task_id, [])
        app_logger.info(f"Retrying task {task_id} with new cookie: {cookie_bundle} (tried: {tried_cookies})")
        append_task_log(task_id, f"Cookie 失效，使用新 Cookie 重试: {cookie_bundle} (第 {task_retry_count[task_id]} 次重试)")
        _start_task_with_cookie(task_id, keyword, max_pages, cookie_bundle)
        return True
    else:
        app_logger.warning(f"No available cookie for retry task {task_id}")
        append_task_log(task_id, "没有可用的 Cookie 进行重试，任务失败")
        update_task(task_id, {"status": "failed"})
        clear_task_history(task_id)
        return False

def process_queued_tasks():
    """处理队列中的任务"""
    tasks = weibo_storage.list_tasks()
    queued_tasks = [t for t in tasks if t.get("status") == "queued"]

    for task in queued_tasks:
        if not can_start_new_task():
            break

        task_id = task.get("id")
        cookie_bundle = allocate_cookie_for_task(task_id)

        if cookie_bundle:
            app_logger.info(f"Starting queued task {task_id} with cookie bundle: {cookie_bundle}")
            _start_task_with_cookie(task_id, task.get("keyword"), task.get("max_pages"), cookie_bundle)
        else:
            app_logger.warning(f"No available cookie bundle for task {task_id}")
            break

# Helper functions
def save_task(task):
    weibo_storage.save_task(task)

def update_task(task_id, mapping):
    weibo_storage.update_task(task_id, mapping)

def get_task(task_id):
    return weibo_storage.get_task(task_id)

def append_task_log(task_id, line):
    weibo_storage.append_log(task_id, line)

def _read_task_log_lines(task_id: int, limit: int = 200):
    # 优先读取日志文件（实际的爬虫日志都在文件中）
    log_path = os.path.join(TASK_LOG_DIR, f"task_{task_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().splitlines()
                return content[-limit:]
        except Exception as exc:
            app_logger.warning(f"Read task log file failed: {exc}")

    # 如果文件不存在或读取失败，才从数据库读取
    lines = weibo_storage.get_logs(task_id, limit)
    return lines if lines else []

def update_batch(batch_id, mapping):
    """更新批次信息"""
    if not weibo_storage.mysql_enabled: return
    db = weibo_storage._get_db()
    try:
        from database.models import WebUIBatch
        batch = db.query(WebUIBatch).filter(WebUIBatch.batch_id == str(batch_id)).first()
        if batch:
            for k, v in mapping.items():
                if k == "task_ids" and isinstance(v, list):
                    v = json.dumps(v)
                if hasattr(batch, k):
                    setattr(batch, k, v)
            db.commit()
    finally:
        db.close()

def _parse_stats_value(value: str):
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    try:
        if text.isdigit():
            return int(text)
        return float(text)
    except ValueError:
        return text

def _get_task_stats_from_redis(task_id: str) -> Dict:
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        prefix = os.getenv("TASK_STATS_PREFIX", "weibo:task:stats:")
        key = f"{prefix}{task_id}"
        data = client.hgetall(key) or {}
        return {k: _parse_stats_value(v) for k, v in data.items()}
    except Exception as exc:
        app_logger.warning(f"Task stats redis read failed: {exc}")
        return {}

def _get_task_stats_from_mysql(task_id: str) -> Dict:
    if not weibo_storage.mysql_enabled:
        return {}
    db = weibo_storage._get_db()
    try:
        from database.models import WebUITask
        task = db.query(WebUITask).filter(WebUITask.task_id == str(task_id)).first()
        if not task:
            return {}
        return {
            "pages_crawled": task.pages_crawled or 0,
            "content_inserted": task.content_inserted or 0,
            "content_updated": task.content_updated or 0,
            "comment_inserted": task.comment_inserted or 0,
            "comment_updated": task.comment_updated or 0,
            "items_count": task.items_count or 0,
        }
    finally:
        db.close()

def _is_process_alive(pid):
    if not pid: return False
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid_value, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

def _refresh_task_status(task):
    if not task or task.get("status") != "running":
        return task
    task_id = task.get("id")
    pid = task.get("pid")
    if not _is_process_alive(pid):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_task(task_id, {"status": "stopped", "finished_at": now, "pid": ""})
        append_task_log(task_id, "任务状态修复：进程不存在，标记为已停止")
        task["status"] = "stopped"
        task["finished_at"] = now
        task["pid"] = ""

        # 释放 cookie 并处理队列
        release_cookie_for_task(task_id)
        app_logger.info(f"Task {task_id} process died, released cookie")

        # 尝试启动队列中的下一个任务
        try:
            process_queued_tasks()
        except Exception as e:
            app_logger.error(f"Error processing queued tasks after refresh: {e}")

    return task

def list_cookies():
    return weibo_storage.list_cookies()

def get_cookie(name):
    return weibo_storage.get_cookie(name)

def save_cookie(name, payload):
    weibo_storage.save_cookie(name, payload)

def delete_cookie(name):
    weibo_storage.delete_cookie(name)

def list_sentiment_words(word_type):
    return weibo_storage.list_sentiment_words(word_type)

def add_sentiment_word(word_type, word):
    weibo_storage.add_sentiment_word(word_type, word)

def get_cookie_bundle(name):
    return weibo_storage.get_cookie_bundle(name)

def get_cookie_string(preferred_bundle_name=""):
    bundle_name = get_cookie_bundle_name(preferred_bundle_name)
    if bundle_name:
        bundle = get_cookie_bundle(bundle_name)
        if bundle and bundle.get("cookie_string"):
            return bundle["cookie_string"]
    return ""

def get_cookie_bundle_name(preferred_bundle_name=""):
    if preferred_bundle_name:
        bundle = get_cookie_bundle(preferred_bundle_name)
        if bundle and bundle.get("cookie_string") and bundle.get("enabled", "1") not in ("0", "false", "False"):
            return preferred_bundle_name
    bundles = weibo_storage.list_cookie_bundles()
    if bundles:
        for bundle in reversed(bundles):
            if bundle and bundle.get("cookie_string") and bundle.get("enabled", "1") not in ("0", "false", "False"):
                return bundle.get("name")
    return ""

def remove_sentiment_word(word_type, word):
    weibo_storage.remove_sentiment_word(word_type, word)

def add_sentiment_words(word_type, words):
    if isinstance(words, str):
        entries = [w.strip() for w in words.splitlines()]
    else:
        entries = [str(w).strip() for w in words]
    for w in [e for e in entries if e]:
        weibo_storage.add_sentiment_word(word_type, w)

def list_cookie_bundles():
    return weibo_storage.list_cookie_bundles()

def save_cookie_bundle(name, cookie_string, proxies, user_agent=""):
    weibo_storage.save_cookie_bundle(name, cookie_string, proxies, user_agent)

def delete_cookie_bundle(name):
    weibo_storage.delete_cookie_bundle(name)

def _update_cookie_bundle_status(name, enabled, status, reason=""):
    weibo_storage.update_cookie_bundle_status(name, enabled, status, reason)

def list_proxies():
    return weibo_storage.list_proxies()

def add_proxy(proxy):
    weibo_storage.add_proxy(proxy)

def add_proxies(proxies):
    if isinstance(proxies, str):
        items = [p.strip() for p in proxies.replace(",", "\n").splitlines() if p.strip()]
    else:
        items = [str(p).strip() for p in proxies if str(p).strip()]
    for p in items:
        weibo_storage.add_proxy(p)

def delete_proxy(proxy):
    weibo_storage.delete_proxy(proxy)

def _validate_cookie_string(cookie_string, user_agent=""):
    if not cookie_string:
        return False, "empty_cookie"
    headers = {"Cookie": cookie_string, "Accept": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    try:
        resp = httpx.get("https://m.weibo.cn/api/config", headers=headers, timeout=10)
        data = resp.json() if resp.text else {}
    except Exception as exc:
        return False, f"request_failed:{exc}"
    login_flag = False
    if isinstance(data, dict):
        login_flag = bool((data.get("data") or {}).get("login") or data.get("login"))
    return login_flag, "ok" if login_flag else "expired"

# Webhook implementation
def get_webhook_config():
    cfg = weibo_storage.get_config("weibo:webhook:config")
    if not cfg:
        return {
            "enabled": False,
            "webhook_url": "",
            "message_template": json.dumps({
                "event": "cookie_validation_failed",
                "cookie_name": "{cookie_name}",
                "status": "{status}",
                "reason": "{reason}",
                "timestamp": "{timestamp}",
            }, ensure_ascii=False),
            "timeout": 10,
            "custom_headers": "{}",
        }
    cfg["enabled"] = str(cfg.get("enabled", "0")) == "1"
    cfg["timeout"] = int(cfg.get("timeout", 10))
    return cfg

def save_webhook_config(webhook_url, enabled=True, message_template=None, timeout=10, custom_headers=None):
    payload = {
        "enabled": "1" if enabled else "0",
        "webhook_url": str(webhook_url),
        "message_template": str(message_template or ""),
        "timeout": str(timeout),
        "custom_headers": str(custom_headers or "{}"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    weibo_storage.save_config("weibo:webhook:config", payload)

def _send_webhook_with_config(cookie_name, status, reason=""):
    config = get_webhook_config()
    if not config.get("enabled") or not config.get("webhook_url"):
        return False, "disabled_or_empty"
    
    webhook_url = config.get("webhook_url")
    try:
        template_dict = json.loads(config.get("message_template", "{}"))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        variables = {"cookie_name": cookie_name, "status": status, "reason": reason, "timestamp": timestamp}
        payload = {}
        for key, value in template_dict.items():
            if isinstance(value, str):
                for var_name, var_value in variables.items():
                    value = value.replace(f"{{{var_name}}}", str(var_value))
            payload[key] = value
        
        headers = json.loads(config.get("custom_headers", "{}"))
        headers.setdefault("Content-Type", "application/json")
        timeout = int(config.get("timeout", 10))
        
        resp = httpx.post(webhook_url, json=payload, timeout=timeout, headers=headers)
        if 200 <= resp.status_code < 300:
            app_logger.info(f"Webhook Notification Success: {cookie_name}")
            return True, "success"
        else:
            return False, f"http_{resp.status_code}"
    except Exception as exc:
        app_logger.error(f"Webhook Notification Error: {exc}")
        return False, str(exc)

def extract_keyword_from_url(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "q" in params: return params["q"][0]
        if "containerid" in params:
            raw = unquote(params["containerid"][0])
            if "q=" in raw: return parse_qs(raw).get("q", [""])[0]
    except: pass
    return ""

def _build_crawler_cmd(keyword, max_pages, with_comments, cookies="", headless=True):
    max_notes = max(int(max_pages), 1) * WEIBO_PAGE_SIZE
    cmd = ["uv", "run", "python", "-u", "main.py", "--platform", "wb", "--type", "search",
           "--keywords", str(keyword), "--get_comment", "true" if with_comments else "false",
           "--save_data_option", "db", "--max_notes", str(max_notes)]
    if headless: cmd.extend(["--headless", "true"])
    if cookies: cmd.extend(["--lt", "cookie", "--cookies", cookies])
    return cmd

def _start_task_with_cookie(task_id, keyword, max_pages, cookie_bundle_name):
    """使用指定的 cookie bundle 启动任务"""
    def _run():
        task = get_task(task_id) or {}
        return_code = None
        try:
            # 获取指定 bundle 的 cookie
            bundle = get_cookie_bundle(cookie_bundle_name)
            cookie_string = bundle.get("cookie_string", "") if bundle else ""

            if not cookie_string:
                append_task_log(task_id, f"警告: Cookie bundle '{cookie_bundle_name}' 没有 cookie 字符串")

            cmd = _build_crawler_cmd(keyword, max_pages, task.get("with_comments", 0), cookie_string)
            append_task_log(task_id, f"启动任务 (Cookie: {cookie_bundle_name}): {' '.join(cmd)}")

            os.makedirs(TASK_LOG_DIR, exist_ok=True)
            log_path = os.path.join(TASK_LOG_DIR, f"task_{task_id}.log")
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"[launcher] started_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"[launcher] cmd={' '.join(cmd)}\n")
            log_file.write(f"[launcher] cwd={ROOT_DIR}\n")
            log_file.flush()

            child_env = {
                **os.environ,
                "CRAWLER_TASK_ID": str(task_id),
                "CRAWLER_TASK_SOURCE": "ui",
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=ROOT_DIR,
                    env=child_env,
                    start_new_session=True,
                    close_fds=True,
                )
            except Exception as exc:
                log_file.write(f"[launcher] spawn_failed: {exc}\n")
                log_file.flush()
                update_task(task_id, {"status": "failed", "pid": ""})
                append_task_log(task_id, f"任务启动失败: {exc}")
                log_file.close()
                return

            update_task(task_id, {
                "status": "running",
                "pid": process.pid,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_key": cookie_bundle_name  # 记录使用的 cookie
            })

            append_task_log(task_id, f"任务日志写入: {log_path}")
            process.wait()
            return_code = process.returncode
            log_file.close()

            # 检查是否需要使用新 Cookie 重试
            if should_retry_with_new_cookie(task_id, return_code):
                append_task_log(task_id, f"检测到 Cookie 可能失效 (返回码: {return_code})，准备使用新 Cookie 重试...")

                # 释放当前 Cookie
                release_cookie_for_task(task_id)

                # 标记 Cookie 为可能失效
                _update_cookie_bundle_status(cookie_bundle_name, False, "expired")

                # 使用新 Cookie 重试
                if retry_task_with_new_cookie(task_id, keyword, max_pages):
                    return  # 重试已启动，不继续执行后续逻辑

            # 任务最终完成或失败
            final_status = "completed" if return_code == 0 else "failed"
            update_task(task_id, {
                "status": final_status,
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pid": ""
            })

            append_task_log(task_id, f"任务{final_status}: 返回码 {return_code}")

            # 清除任务历史
            clear_task_history(task_id)

        except Exception as exc:
            append_task_log(task_id, f"任务执行错误: {exc}")
            update_task(task_id, {"status": "failed", "pid": ""})
            clear_task_history(task_id)

        finally:
            # 释放 cookie 并处理队列中的任务
            release_cookie_for_task(task_id)
            app_logger.info(f"Task {task_id} finished, released cookie: {cookie_bundle_name}")

            # 尝试启动队列中的下一个任务
            try:
                process_queued_tasks()
            except Exception as e:
                app_logger.error(f"Error processing queued tasks: {e}")

    threading.Thread(target=_run, daemon=True).start()

def start_task(task_id, keyword, max_pages):
    """启动任务（带并发控制和 cookie 分配）"""
    # 检查是否可以立即启动
    if can_start_new_task():
        cookie_bundle = allocate_cookie_for_task(task_id)

        if cookie_bundle:
            app_logger.info(f"Starting task {task_id} with cookie bundle: {cookie_bundle}")
            _start_task_with_cookie(task_id, keyword, max_pages, cookie_bundle)
        else:
            # 没有可用的 cookie，加入队列
            app_logger.info(f"No available cookie for task {task_id}, queuing...")
            update_task(task_id, {"status": "queued"})
            append_task_log(task_id, "任务已加入队列，等待可用的 Cookie...")
    else:
        # 达到并发限制，加入队列
        app_logger.info(f"Max concurrent tasks reached, queuing task {task_id}")
        update_task(task_id, {"status": "queued"})
        append_task_log(task_id, f"任务已加入队列，当前运行任务数: {get_running_tasks_count()}/{MAX_CONCURRENT_TASKS}")

def stop_task(task_id, pid):
    if not pid: return False, "no_pid"
    try:
        os.kill(int(pid), signal.SIGTERM)
        update_task(task_id, {"status": "stopped", "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pid": ""})

        # 释放 cookie 并处理队列
        release_cookie_for_task(task_id)
        app_logger.info(f"Task {task_id} stopped, released cookie")

        # 尝试启动队列中的下一个任务
        try:
            process_queued_tasks()
        except Exception as e:
            app_logger.error(f"Error processing queued tasks after stop: {e}")

        return True, None
    except:
        return False, "kill_failed"

# ========================================
# API Routes
# ========================================

@router.get("/cookies")
async def list_cookies_route(): return list_cookies()

@router.post("/cookies")
async def add_cookie_route(request: Request):
    data = await request.json()
    name = data.get("name")
    if not name: return JSONResponse({"error": "missing name"}, status_code=400)
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_cookie(name, data)
    return {"success": True, "cookies": list_cookies()}

@router.delete("/cookies")
async def delete_cookie_route(name: str):
    delete_cookie(name); return {"success": True, "cookies": list_cookies()}

@router.get("/cookie_bundles")
async def list_cookie_bundles_route(): return list_cookie_bundles()

@router.post("/cookie_bundles")
async def add_cookie_bundle_route(request: Request):
    data = await request.json()
    name = data.get("name")
    if not name or not data.get("cookie_string"): return JSONResponse({"error": "invalid"}, status_code=400)
    save_cookie_bundle(name, data.get("cookie_string"), data.get("proxies", []), data.get("user_agent", ""))
    return {"success": True, "bundles": list_cookie_bundles()}

@router.delete("/cookie_bundles")
async def delete_cookie_bundle_route(name: str):
    delete_cookie_bundle(name); return {"success": True, "bundles": list_cookie_bundles()}

@router.post("/cookie_bundles/{name}/validate")
async def validate_cookie_bundle_route(name: str):
    bundle = get_cookie_bundle(name)
    if not bundle: return JSONResponse({"error": "not_found"}, status_code=404)
    ok, status = _validate_cookie_string(bundle.get("cookie_string", ""), bundle.get("user_agent", ""))
    _update_cookie_bundle_status(name, ok, status)
    return {"success": True, "valid": ok, "status": status}

@router.post("/cookie_bundles/validate_all")
async def validate_all_cookie_bundles_route():
    """批量验证所有 Cookie Bundle"""
    bundles = list_cookie_bundles()
    validated_count = 0
    success_count = 0
    failed_count = 0

    for bundle in bundles:
        name = bundle.get("name")
        if not name:
            continue

        validated_count += 1
        ok, status = _validate_cookie_string(bundle.get("cookie_string", ""), bundle.get("user_agent", ""))
        _update_cookie_bundle_status(name, ok, status)

        if ok:
            success_count += 1
        else:
            failed_count += 1
            # 发送 webhook 通知（如果配置了）
            _send_webhook_with_config(name, status, "cookie validation failed")

    return {
        "success": True,
        "validated": validated_count,
        "success_count": success_count,
        "failed_count": failed_count
    }

@router.get("/tasks")
async def list_tasks_route():
    return [_refresh_task_status(t) for t in weibo_storage.list_tasks()]

@router.get("/tasks/queue/status")
async def get_queue_status_route():
    """获取任务队列状态"""
    tasks = weibo_storage.list_tasks()
    running_tasks = [t for t in tasks if t.get("status") == "running"]
    queued_tasks = [t for t in tasks if t.get("status") == "queued"]

    # 获取 cookie 使用情况
    with task_queue_lock:
        cookie_usage = dict(running_task_cookies)

    return {
        "max_concurrent": MAX_CONCURRENT_TASKS,
        "running_count": len(running_tasks),
        "queued_count": len(queued_tasks),
        "running_tasks": [{"id": t.get("id"), "keyword": t.get("keyword"), "cookie": cookie_usage.get(t.get("id"))} for t in running_tasks],
        "queued_tasks": [{"id": t.get("id"), "keyword": t.get("keyword")} for t in queued_tasks],
        "cookie_usage": cookie_usage
    }

@router.post("/tasks")
async def create_task_route(request: Request):
    data = await request.json()
    task_id = weibo_storage.get_next_id(TASK_ID_KEY)
    new_task = {
        "id": task_id, "keyword": data.get("keyword", "Python"),
        "max_pages": data.get("max_pages", DEFAULT_PAGE_SIZE),
        "with_comments": 1 if data.get("with_comments") else 0,
        "status": "pending", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items_count": 0, "pid": ""
    }
    save_task(new_task)
    start_task(task_id, new_task["keyword"], new_task["max_pages"])
    return {"success": True, "task": new_task}

@router.post("/tasks/{task_id}/start")
async def start_task_route(task_id: int):
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "task_not_found"}, status_code=404)
    if task.get("status") == "running":
        return {"success": True, "started": False, "reason": "already_running"}
    start_task(task_id, task.get("keyword"), task.get("max_pages"))
    return {"success": True, "started": True}

@router.delete("/tasks/{task_id}")
async def delete_task_route(task_id: int):
    weibo_storage.delete_task(task_id); return {"success": True}

@router.post("/tasks/{task_id}/stop")
async def stop_task_route(task_id: int):
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "task_not_found"}, status_code=404)
    ok, reason = stop_task(task_id, task.get("pid"))
    if ok:
        return {"success": True}
    return JSONResponse({"error": reason or "stop_failed"}, status_code=400)

@router.get("/tasks/{task_id}/logs")
async def task_logs_route(task_id: int, limit: int = 200):
    lines = _read_task_log_lines(task_id, limit)
    return {"total": len(lines), "lines": lines}

@router.get("/tasks/{task_id}/stats")
async def task_stats_route(task_id: int):
    stats = {
        "pages_crawled": 0,
        "content_inserted": 0,
        "content_updated": 0,
        "comment_inserted": 0,
        "comment_updated": 0,
        "items_count": 0,
        "duration_seconds": 0,
        "search_seconds": 0,
        "full_text_seconds": 0,
        "comments_seconds": 0,
        "sleep_seconds": 0,
    }
    stats.update(_get_task_stats_from_mysql(str(task_id)))
    stats.update(_get_task_stats_from_redis(str(task_id)))
    return stats

@router.get("/proxies")
async def list_proxies_route(): return list_proxies()

@router.post("/proxies")
async def add_proxy_route(request: Request):
    data = await request.json()
    if data.get("proxies"): add_proxies(data.get("proxies"))
    elif data.get("proxy"): add_proxy(data.get("proxy"))
    return {"success": True, "proxies": list_proxies()}

@router.delete("/proxies")
async def delete_proxy_route(proxy: str):
    delete_proxy(proxy); return {"success": True, "proxies": list_proxies()}

@router.get("/sentiment/words")
async def list_sentiment_word_group_route(word_type: str = ""):
    types = ["positive", "negative", "negation", "degree", "stopwords"]
    if word_type:
        if word_type not in types: return JSONResponse({"error": "invalid"}, status_code=400)
        return list_sentiment_words(word_type)
    return {t: list_sentiment_words(t) for t in types}

@router.post("/sentiment/words")
async def add_sentiment_route(request: Request):
    data = await request.json()
    w_type, word, words = data.get("type"), data.get("word"), data.get("words")
    if not w_type or (not word and not words): return JSONResponse({"error": "invalid"}, status_code=400)
    if words: add_sentiment_words(w_type, words)
    else: add_sentiment_word(w_type, word)
    return {"success": True}

@router.delete("/sentiment/words")
async def delete_sentiment_route(word_type: str, word: str):
    remove_sentiment_word(word_type, word); return {"success": True}

@router.get("/webhook/config")
async def get_webhook_config_route():
    config = get_webhook_config()
    return {"success": True, "config": config}

@router.post("/webhook/config")
@router.put("/webhook/config")
async def save_webhook_config_route(request: Request):
    data = await request.json()
    save_webhook_config(data.get("webhook_url"), data.get("enabled", True), data.get("message_template"),
                        data.get("timeout", 10), data.get("custom_headers"))
    return {"success": True}

@router.post("/webhook/test")
async def test_webhook_route(request: Request):
    data = await request.json()

    # 从配置中读取 webhook URL
    config = get_webhook_config()
    webhook_url = config.get("webhook_url")

    if not webhook_url:
        return JSONResponse({"error": "webhook_url_not_configured", "message": "请先配置 Webhook URL"}, status_code=400)

    # 获取测试参数
    cookie_name = data.get("cookie_name", "test_cookie")
    status = data.get("status", "expired")
    reason = data.get("reason", "测试通知")

    # 构造测试消息
    try:
        import httpx

        # 使用配置的消息模板或默认模板
        message_template = config.get("message_template", "")
        if message_template:
            try:
                # 尝试解析并使用配置的模板
                template_obj = json.loads(message_template)
                # 替换模板中的变量
                template_str = json.dumps(template_obj)
                template_str = template_str.replace("{cookie_name}", cookie_name)
                template_str = template_str.replace("{status}", status)
                template_str = template_str.replace("{reason}", reason)
                template_str = template_str.replace("{timestamp}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                test_payload = json.loads(template_str)
            except:
                # 模板解析失败，使用默认模板
                test_payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": f"## Webhook 测试\n\n> Cookie 名称: {cookie_name}\n> 状态: {status}\n> 原因: {reason}\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }
        else:
            # 使用默认模板
            test_payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"## Webhook 测试\n\n> Cookie 名称: {cookie_name}\n> 状态: {status}\n> 原因: {reason}\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            }

        # 发送测试消息
        timeout = int(config.get("timeout", 10))
        custom_headers = {}
        try:
            custom_headers_str = config.get("custom_headers", "{}")
            custom_headers = json.loads(custom_headers_str) if custom_headers_str else {}
        except:
            pass

        headers = {"Content-Type": "application/json"}
        headers.update(custom_headers)

        resp = httpx.post(webhook_url, json=test_payload, timeout=timeout, headers=headers)
        if resp.status_code == 200:
            return {"success": True, "message": "测试成功"}
        else:
            return JSONResponse({"error": f"HTTP {resp.status_code}", "message": f"Webhook 返回错误: {resp.status_code}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e), "message": f"发送失败: {str(e)}"}, status_code=400)

@router.get("/schedule/config")
async def get_schedule_config_route():
    cfg = weibo_storage.get_config("weibo:schedule:config")
    if not cfg:
        cfg = {"enabled": False, "cron_expression": "0 */1 * * *"}
    else:
        # 转换 enabled 为布尔值
        cfg["enabled"] = str(cfg.get("enabled", "0")) in ("1", "true", "True")
    return {"success": True, "config": cfg}

@router.post("/schedule/config")
@router.put("/schedule/config")
async def save_schedule_config_route(request: Request):
    data = await request.json()
    weibo_storage.save_config("weibo:schedule:config", {
        "enabled": "1" if data.get("enabled", False) else "0",
        "cron_expression": data.get("cron_expression", "0 */1 * * *")
    })
    return {"success": True}

@router.get("/cookie_check/schedule/config")
async def get_cookie_check_schedule_config_route():
    cfg = weibo_storage.get_config("weibo:cookie_check:schedule:config")
    if not cfg:
        cfg = {"enabled": False, "cron_expression": "0 */1 * * *"}
    else:
        # 转换 enabled 为布尔值
        cfg["enabled"] = str(cfg.get("enabled", "0")) in ("1", "true", "True")
    return {"success": True, "config": cfg}

@router.post("/cookie_check/schedule/config")
@router.put("/cookie_check/schedule/config")
async def save_cookie_check_schedule_config_route(request: Request):
    data = await request.json()
    weibo_storage.save_config("weibo:cookie_check:schedule:config", {
        "enabled": "1" if data.get("enabled", False) else "0",
        "cron_expression": data.get("cron_expression", "0 */1 * * *")
    })
    return {"success": True}

@router.post("/cookie_check/schedule/trigger")
async def trigger_cookie_check_route():
    """手动触发 Cookie 检查"""
    # TODO: 实现 Cookie 检查逻辑
    return {"success": True, "message": "Cookie 检查已触发"}

# Batch Management Routes
@router.get("/batches")
async def list_batches_route(limit: int = 50):
    """获取批次列表"""
    batches = weibo_storage.list_batches(limit)
    return {"success": True, "batches": batches}

@router.post("/batch/execute")
async def execute_batch_route(request: Request):
    """批量执行监控任务"""
    data = await request.json()
    ms_types = data.get("ms_types", "11")

    # 创建新批次
    batch_id = weibo_storage.get_next_id(BATCH_ID_KEY)
    batch_data = {
        "batch_id": batch_id,
        "name": f"批次执行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_ids": [],
        "template_count": 0,
        "completed_count": 0,
        "failed_count": 0
    }
    weibo_storage.save_batch(batch_data)

    # 启动后台任务处理批次
    def _execute_batch():
        try:
            weibo_storage.append_batch_log(batch_id, f"开始执行批次任务，类型: {ms_types}")

            # 获取监控任务列表
            if not monitor_engine:
                weibo_storage.append_batch_log(batch_id, "错误: 监控数据库未启用")
                update_batch(batch_id, {"status": "failed"})
                return

            ms_type_list = ms_types.split(",")
            sql = text(f"select * from web_monitorspider where ms_type in :types and ms_status = 1 order by ms_id")

            with monitor_engine.connect() as conn:
                rows = conn.execute(sql, {"types": tuple(ms_type_list)}).mappings().fetchall()
                tasks = [dict(r) for r in rows]

            weibo_storage.append_batch_log(batch_id, f"找到 {len(tasks)} 个待执行任务")
            update_batch(batch_id, {
                "template_count": len(tasks),
                "status": "running"
            })

            task_ids = []
            completed = 0
            failed = 0

            # 为每个监控任务创建爬取任务
            for task in tasks:
                try:
                    keyword = extract_keyword_from_url(task.get("ms_start_url", ""))
                    if not keyword:
                        keyword = task.get("ms_keys", "Python")

                    # 创建任务
                    task_id = weibo_storage.get_next_id(TASK_ID_KEY)
                    new_task = {
                        "id": task_id,
                        "keyword": keyword,
                        "max_pages": DEFAULT_PAGE_SIZE,
                        "with_comments": 1,
                        "status": "pending",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "items_count": 0,
                        "pid": ""
                    }
                    save_task(new_task)
                    task_ids.append(task_id)

                    # 启动任务
                    start_task(task_id, new_task["keyword"], new_task["max_pages"])
                    weibo_storage.append_batch_log(batch_id, f"已创建任务 {task_id}: {keyword}")
                    completed += 1

                except Exception as e:
                    weibo_storage.append_batch_log(batch_id, f"创建任务失败: {str(e)}")
                    failed += 1

            # 更新批次状态
            update_batch(batch_id, {
                "task_ids": task_ids,
                "completed_count": completed,
                "failed_count": failed,
                "status": "completed"
            })
            weibo_storage.append_batch_log(batch_id, f"批次执行完成: 成功 {completed}, 失败 {failed}")

        except Exception as exc:
            weibo_storage.append_batch_log(batch_id, f"批次执行错误: {str(exc)}")
            update_batch(batch_id, {"status": "failed"})

    threading.Thread(target=_execute_batch, daemon=True).start()
    return {"success": True, "batch_id": batch_id}

@router.get("/batches/{batch_id}/logs")
async def get_batch_logs_route(batch_id: int, limit: int = 200):
    """获取批次日志"""
    logs = weibo_storage.get_logs(f"batch_{batch_id}", limit)
    return {"success": True, "logs": logs}

@router.post("/batches/{batch_id}/stop")
async def stop_batch_route(batch_id: int):
    """停止批次及其关联的所有任务"""
    db = weibo_storage._get_db()
    try:
        from database.models import WebUIBatch
        batch = db.query(WebUIBatch).filter(WebUIBatch.batch_id == str(batch_id)).first()
        if not batch:
            return JSONResponse({"error": "batch_not_found"}, status_code=404)

        # 更新批次状态
        batch.status = "stopped"
        db.commit()
        weibo_storage.append_batch_log(batch_id, "批次已手动停止")

        # 获取批次关联的任务列表
        stopped_count = 0
        try:
            task_ids = json.loads(batch.task_ids) if batch.task_ids else []

            # 停止所有关联的任务
            for task_id in task_ids:
                task = get_task(task_id)
                if task and task.get("status") == "running":
                    pid = task.get("pid")
                    if pid:
                        success, _ = stop_task(task_id, pid)
                        if success:
                            stopped_count += 1
        except Exception as e:
            app_logger.error(f"停止批次任务失败: {e}")

        return {"success": True, "stopped_count": stopped_count}
    finally:
        db.close()

@router.get("/processes")
async def list_processes_route():
    """获取运行中的爬虫进程列表"""
    tasks = weibo_storage.list_tasks()
    running_tasks = [t for t in tasks if t.get("status") == "running"]

    processes = []
    for task in running_tasks:
        task = _refresh_task_status(task)
        if task.get("status") != "running":
            continue

        pid = task.get("pid")
        process_info = {}

        # 尝试获取进程信息
        if pid and _is_process_alive(pid):
            try:
                import psutil
                p = psutil.Process(int(pid))
                # 获取运行时间
                create_time = p.create_time()
                import time
                elapsed = int(time.time() - create_time)
                hours = elapsed // 3600
                minutes = (elapsed % 3600) // 60
                seconds = elapsed % 60
                etime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                # 获取命令
                cmdline = " ".join(p.cmdline())

                process_info = {
                    "etime": etime,
                    "command": cmdline
                }
            except:
                pass

        processes.append({
            "task_id": task.get("id"),
            "keyword": task.get("keyword"),
            "status": task.get("status"),
            "pid": pid,
            "process": process_info
        })

    return processes

@router.get("/logs")
async def get_system_logs_route(limit: int = 300):
    """获取系统日志（从日志文件中读取）"""
    try:
        log_lines = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                # 读取最后 N 行
                all_lines = f.readlines()
                log_lines = [line.rstrip() for line in all_lines[-limit:]]
        return {"lines": log_lines, "total": len(log_lines)}
    except Exception as e:
        app_logger.error(f"读取系统日志失败: {e}")
        return {"lines": [f"读取日志失败: {str(e)}"], "total": 0}

# Monitor related (Sync with monitor engine)
@router.get("/monitor/tasks")
async def list_monitor_tasks(ms_types: str = "11", page: int = 1, page_size: int = 50, keyword: str = ""):
    if not monitor_engine: return JSONResponse({"error": "monitor_mysql_disabled"}, status_code=400)
    ms_type_list = ms_types.split(",")
    offset = (max(page, 1) - 1) * page_size
    keyword = (keyword or "").strip()
    where = "where ms_type in :types"
    if keyword: where += " and (ms_keys like :kw or ms_start_url like :kw)"
    sql = text(f"select * from web_monitorspider {where} order by ms_modify_date desc limit :limit offset :offset")
    count_sql = text(f"select count(*) from web_monitorspider {where}")
    params = {"types": tuple(ms_type_list), "limit": page_size, "offset": offset}
    if keyword: params["kw"] = f"%{keyword}%"
    try:
        with monitor_engine.connect() as conn:
            total = conn.execute(count_sql, params).scalar() or 0
            rows = conn.execute(sql, params).mappings()
            return {"total": total, "page": page, "page_size": page_size, "tasks": [dict(r) for r in rows]}
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/monitor/tasks/{ms_id}/status")
async def update_monitor_task_status(ms_id: int, request: Request):
    if not monitor_engine: return JSONResponse({"error": "disabled"}, status_code=400)
    data = await request.json()
    status = int(data.get("status", 0))
    sql = text("update web_monitorspider set ms_status = :status, ms_modify_date = now() where ms_id = :ms_id")
    try:
        with monitor_engine.begin() as conn:
            conn.execute(sql, {"status": status, "ms_id": ms_id})
        return {"success": True}
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/monitor/tasks/stop_all")
async def stop_all_monitor_tasks_route(request: Request):
    """停止所有监控任务"""
    if not monitor_engine: return JSONResponse({"error": "disabled"}, status_code=400)

    data = await request.json()
    ms_types = data.get("ms_types", "11")
    keyword = data.get("keyword", "").strip()

    ms_type_list = ms_types.split(",")
    where = "where ms_type in :types and ms_status = 1"
    if keyword:
        where += " and (ms_keys like :kw or ms_start_url like :kw)"

    sql = text(f"update web_monitorspider set ms_status = 0, ms_modify_date = now() {where}")
    params = {"types": tuple(ms_type_list)}
    if keyword:
        params["kw"] = f"%{keyword}%"

    try:
        with monitor_engine.begin() as conn:
            result = conn.execute(sql, params)
            updated = result.rowcount
        return {"success": True, "updated": updated}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def init_scheduler():
    app_logger.info("Initializing Weibo Scheduler (MySQL Backend)")

    # 初始化任务队列
    init_task_queue()

    # Schedule loading logic...
    pass
