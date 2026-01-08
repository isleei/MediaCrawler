# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/weibo_ui.py
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
from urllib.parse import parse_qs, unquote, urlparse

import redis
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

router = APIRouter(prefix="/weibo/api", tags=["weibo-ui"])

DATA_DIR = "data"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "web.log")

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

COOKIE_PREFIX = os.getenv("COOKIE_PREFIX", "weibo:cookie:")
COOKIE_INDEX_LIST = os.getenv("COOKIE_INDEX_LIST", "weibo:cookies")
COOKIE_INDEX_SET = os.getenv("COOKIE_INDEX_SET", "weibo:cookies:set")
COOKIE_BUNDLE_PREFIX = os.getenv("COOKIE_BUNDLE_PREFIX", "weibo:cookie:bundle:")
COOKIE_BUNDLE_INDEX_LIST = os.getenv("COOKIE_BUNDLE_INDEX_LIST", "weibo:cookie:bundles")
COOKIE_BUNDLE_INDEX_SET = os.getenv("COOKIE_BUNDLE_INDEX_SET", "weibo:cookie:bundles:set")
DEFAULT_COOKIE_BUNDLE_NAME = os.getenv("WEIBO_COOKIE_BUNDLE_NAME", "")
MONITOR_COOKIE_BUNDLE_NAME = os.getenv("MONITOR_COOKIE_BUNDLE_NAME", "")
TASK_ID_KEY = os.getenv("TASK_ID_KEY", "weibo:task:id")
TASK_INDEX_LIST = os.getenv("TASK_INDEX_LIST", "weibo:tasks")
TASK_INDEX_SET = os.getenv("TASK_INDEX_SET", "weibo:tasks:set")
TASK_LOG_PREFIX = os.getenv("TASK_LOG_PREFIX", "weibo:task:logs:")
REDIS_TASK_DATA_PREFIX = os.getenv("REDIS_TASK_DATA_PREFIX", "weibo:task:data:")
SENTI_REDIS_PREFIX = os.getenv("SENTI_REDIS_PREFIX", "weibo:senti:")
TASK_STATS_PREFIX = os.getenv("TASK_STATS_PREFIX", "weibo:task:stats:")
PROXY_INDEX_LIST = os.getenv("PROXY_INDEX_LIST", "weibo:proxies")
PROXY_INDEX_SET = os.getenv("PROXY_INDEX_SET", "weibo:proxies:set")
TASK_SPIDER_AUTOSTART = os.getenv("MONITOR_SPIDER_AUTOSTART", "1") not in (
    "0",
    "false",
    "False",
)
TASK_SPIDER_CMD = os.getenv(
    "MONITOR_TASK_SPIDER_CMD", "uv run python main.py --platform wb --type search"
)
TASK_SPIDER_LOCK_PREFIX = os.getenv("MONITOR_TASK_SPIDER_LOCK_PREFIX", "weibo:task:running:")

DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_MAX_PAGES", "5"))
WEIBO_PAGE_SIZE = int(os.getenv("WEIBO_PAGE_SIZE", "10"))

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "127.0.0.1"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True,
)

_monitor_mysql_flag = os.getenv("MONITOR_MYSQL_ENABLED")
MONITOR_MYSQL_ENABLED = True if _monitor_mysql_flag is None else _monitor_mysql_flag in (
    "1",
    "true",
    "True",
)
MONITOR_MYSQL_HOST = os.getenv("MONITOR_MYSQL_HOST", os.getenv("MYSQL_DB_HOST", "127.0.0.1"))
MONITOR_MYSQL_PORT = int(os.getenv("MONITOR_MYSQL_PORT", os.getenv("MYSQL_DB_PORT", "3306")))
MONITOR_MYSQL_DBNAME = os.getenv("MONITOR_MYSQL_DBNAME", os.getenv("MYSQL_DB_NAME", "yuqing"))
MONITOR_MYSQL_USER = os.getenv("MONITOR_MYSQL_USER", os.getenv("MYSQL_DB_USER", "root"))
MONITOR_MYSQL_PASSWORD = os.getenv("MONITOR_MYSQL_PASSWORD", os.getenv("MYSQL_DB_PWD", ""))
MONITOR_MYSQL_CHARSET = os.getenv("MONITOR_MYSQL_CHARSET", os.getenv("MYSQL_CHARSET", "utf8mb4"))

monitor_engine = None
if MONITOR_MYSQL_ENABLED:
    # Use utility function to create engine with safe password handling
    from database.db_utils import create_mysql_engine_safe

    monitor_engine = create_mysql_engine_safe(
        host=MONITOR_MYSQL_HOST,
        port=MONITOR_MYSQL_PORT,
        user=MONITOR_MYSQL_USER,
        password=MONITOR_MYSQL_PASSWORD,
        database=MONITOR_MYSQL_DBNAME,
        charset=MONITOR_MYSQL_CHARSET,
    )


def task_key(task_id):
    return f"weibo:task:{task_id}"


def cookie_key(name):
    return f"{COOKIE_PREFIX}{name}"


def task_log_key(task_id):
    return f"{TASK_LOG_PREFIX}{task_id}"


def task_data_key(task_id):
    return f"{REDIS_TASK_DATA_PREFIX}{task_id}"


def task_stats_key(task_id):
    return f"{TASK_STATS_PREFIX}{task_id}"


def cookie_bundle_key(name):
    return f"{COOKIE_BUNDLE_PREFIX}{name}"


def sentiment_key(word_type):
    return f"{SENTI_REDIS_PREFIX}{word_type}"


def save_task(task):
    task_id = task["id"]
    key = task_key(task_id)
    mapping = {k: str(v) for k, v in task.items()}
    redis_client.hset(key, mapping=mapping)
    if redis_client.sadd(TASK_INDEX_SET, str(task_id)):
        redis_client.rpush(TASK_INDEX_LIST, str(task_id))
    redis_client.delete(task_log_key(task_id))
    redis_client.delete(task_stats_key(task_id))


def update_task(task_id, mapping):
    key = task_key(task_id)
    redis_client.hset(key, mapping={k: str(v) for k, v in mapping.items()})


def get_task(task_id):
    data = redis_client.hgetall(task_key(task_id))
    if not data:
        return None
    return normalize_task(data)


def normalize_task(data):
    task = dict(data)
    task["id"] = int(task["id"])
    task["max_pages"] = int(task.get("max_pages", 0))
    task["items_count"] = int(task.get("items_count", 0))
    task["with_comments"] = int(task.get("with_comments", 0))
    return task


def append_task_log(task_id, line):
    if line is None:
        return
    key = task_log_key(task_id)
    redis_client.rpush(key, line)


def _is_process_alive(pid):
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        if os.name != "nt":
            os.kill(pid_value, 0)
        else:
            os.kill(pid_value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _refresh_task_status(task):
    if not task or task.get("status") != "running":
        return task
    task_id = task.get("id")
    pid = task.get("pid")
    if not _is_process_alive(pid):
        proc = None
        keyword = (task.get("keyword") or "").strip()
        if keyword:
            for item in _list_crawler_processes():
                if item.get("keyword") == keyword:
                    proc = item
                    break
        if proc:
            update_task(task_id, {"pid": proc.get("pid")})
            task["pid"] = proc.get("pid")
            return task
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_task(task_id, {"status": "stopped", "finished_at": now, "pid": ""})
        append_task_log(task_id, "任务状态修复：进程不存在，标记为已停止")
        task["status"] = "stopped"
        task["finished_at"] = now
        task["pid"] = ""
    return task


def _fetch_process_info(pid):
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,pgid=,etime=,command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    output = (result.stdout or "").strip()
    if not output:
        return None
    parts = output.split(None, 4)
    if len(parts) < 5:
        return None
    return {
        "pid": parts[0],
        "ppid": parts[1],
        "pgid": parts[2],
        "etime": parts[3],
        "command": parts[4],
    }


def _mask_command(command):
    if not command:
        return command
    if "--cookies" not in command:
        return command
    parts = command.split("--cookies", 1)
    return f"{parts[0]}--cookies ***"


def _extract_keyword_from_cmd(command):
    if not command:
        return ""
    try:
        match = re.search(r"--keywords\s+([^\s]+)", command)
    except re.error:
        return ""
    return match.group(1) if match else ""


def _list_crawler_processes():
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid=,pgid=,etime=,command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    output = (result.stdout or "").strip()
    if not output:
        return []
    processes = []
    for line in output.splitlines():
        if "main.py" not in line or "--platform" not in line or "--type" not in line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        raw_command = parts[4]
        processes.append(
            {
                "pid": parts[0],
                "ppid": parts[1],
                "pgid": parts[2],
                "etime": parts[3],
                "command": _mask_command(raw_command),
                "keyword": _extract_keyword_from_cmd(raw_command),
            }
        )
    return processes


def list_cookies():
    names = redis_client.lrange(COOKIE_INDEX_LIST, 0, -1)
    cookies = []
    for name in names:
        cookie = get_cookie(name)
        if cookie:
            cookies.append(cookie)
    return cookies


def get_cookie(name):
    data = redis_client.hgetall(cookie_key(name))
    if not data:
        return None
    data.setdefault("enabled", "1")
    data.setdefault("status", "unknown")
    return dict(data)


def save_cookie(name, payload):
    key = cookie_key(name)
    payload = {k: str(v) for k, v in payload.items()}
    payload.setdefault("enabled", "1")
    payload.setdefault("status", "unknown")
    redis_client.hset(key, mapping=payload)
    if redis_client.sadd(COOKIE_INDEX_SET, name):
        redis_client.rpush(COOKIE_INDEX_LIST, name)


def delete_cookie(name):
    redis_client.delete(cookie_key(name))
    redis_client.lrem(COOKIE_INDEX_LIST, 0, name)
    redis_client.srem(COOKIE_INDEX_SET, name)


def list_sentiment_words(word_type):
    return sorted(redis_client.smembers(sentiment_key(word_type)))


def add_sentiment_word(word_type, word):
    redis_client.sadd(sentiment_key(word_type), word)


def get_cookie_bundle(name):
    data = redis_client.hgetall(cookie_bundle_key(name))
    if not data:
        return None
    return dict(data)


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
        if bundle and bundle.get("cookie_string") and bundle.get("enabled", "1") not in (
            "0",
            "false",
            "False",
        ):
            return preferred_bundle_name

    names = redis_client.lrange(COOKIE_BUNDLE_INDEX_LIST, 0, -1)
    if names:
        for name in reversed(names):
            bundle = get_cookie_bundle(name)
            if bundle and bundle.get("cookie_string") and bundle.get("enabled", "1") not in (
                "0",
                "false",
                "False",
            ):
                return name

    return ""


def remove_sentiment_word(word_type, word):
    redis_client.srem(sentiment_key(word_type), word)


def add_sentiment_words(word_type, words):
    if isinstance(words, str):
        entries = [w.strip() for w in words.splitlines()]
    else:
        entries = [str(w).strip() for w in words]
    entries = [w for w in entries if w]
    if entries:
        redis_client.sadd(sentiment_key(word_type), *entries)


def list_cookie_bundles():
    names = redis_client.lrange(COOKIE_BUNDLE_INDEX_LIST, 0, -1)
    bundles = []
    for name in names:
        data = redis_client.hgetall(cookie_bundle_key(name))
        if data:
            data.setdefault("enabled", "1")
            data.setdefault("status", "unknown")
            bundles.append(data)
    return bundles


def save_cookie_bundle(name, cookie_string, proxies, user_agent=""):
    key = cookie_bundle_key(name)
    proxy_list = []
    if isinstance(proxies, str):
        proxy_list = [p.strip() for p in proxies.replace(",", "\n").splitlines() if p.strip()]
    elif isinstance(proxies, list):
        proxy_list = [str(p).strip() for p in proxies if str(p).strip()]
    proxies_value = json.dumps(proxy_list, ensure_ascii=False) if proxy_list else ""
    payload = {
        "name": str(name),
        "cookie_string": str(cookie_string),
        "proxies": proxies_value,
        "user_agent": str(user_agent or ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "enabled": "1",
        "status": "unknown",
    }
    redis_client.hset(key, mapping=payload)
    if redis_client.sadd(COOKIE_BUNDLE_INDEX_SET, name):
        redis_client.rpush(COOKIE_BUNDLE_INDEX_LIST, name)


def delete_cookie_bundle(name):
    redis_client.delete(cookie_bundle_key(name))
    redis_client.lrem(COOKIE_BUNDLE_INDEX_LIST, 0, name)
    redis_client.srem(COOKIE_BUNDLE_INDEX_SET, name)


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


def _update_cookie_bundle_status(name, enabled, status, reason=""):
    key = cookie_bundle_key(name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mapping = {
        "enabled": "1" if enabled else "0",
        "status": status,
        "last_checked_at": now,
    }
    if reason:
        mapping["last_check_reason"] = reason
    redis_client.hset(key, mapping=mapping)




def list_proxies():
    return redis_client.lrange(PROXY_INDEX_LIST, 0, -1)


def add_proxy(proxy):
    if redis_client.sadd(PROXY_INDEX_SET, proxy):
        redis_client.rpush(PROXY_INDEX_LIST, proxy)


def add_proxies(proxies):
    if isinstance(proxies, str):
        items = [p.strip() for p in proxies.splitlines()]
    else:
        items = [str(p).strip() for p in proxies]
    items = [p for p in items if p]
    for proxy in items:
        add_proxy(proxy)


def delete_proxy(proxy):
    redis_client.lrem(PROXY_INDEX_LIST, 0, proxy)
    redis_client.srem(PROXY_INDEX_SET, proxy)


def extract_keyword_from_url(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "q" in params:
            return params["q"][0]
        if "containerid" in params:
            raw = unquote(params["containerid"][0])
            if "q=" in raw:
                return parse_qs(raw).get("q", [""])[0]
    except Exception:
        return ""
    return ""


def upsert_task_from_monitor(row, status):
    ms_id = int(row["ms_id"])
    keyword = row.get("ms_keys") or extract_keyword_from_url(row.get("ms_start_url") or "") or ""
    max_pages = int(os.getenv("DEFAULT_MAX_PAGES", str(DEFAULT_PAGE_SIZE)))
    with_comments = os.getenv("MONITOR_DEFAULT_WITH_COMMENTS", "1") in ("1", "true", "True")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = get_task(ms_id) or {}
    payload = {
        "id": ms_id,
        "keyword": keyword,
        "max_pages": max_pages,
        "with_comments": 1 if with_comments else 0,
        "status": status,
        "created_at": existing.get("created_at") if existing else now,
        "started_at": now if status == "running" else (existing.get("started_at") if existing else ""),
        "finished_at": existing.get("finished_at") if existing else "",
        "items_count": existing.get("items_count") if existing else 0,
        "output_file": existing.get("output_file") if existing else "",
        "data_key": task_data_key(ms_id),
    }
    save_task(payload)


def _build_crawler_cmd(keyword, max_pages, with_comments, cookies="", headless=True):
    max_notes = max(int(max_pages), 1) * WEIBO_PAGE_SIZE
    cmd = [
        "uv",
        "run",
        "python",
        "main.py",
        "--platform",
        "wb",
        "--type",
        "search",
        "--keywords",
        str(keyword),
        "--get_comment",
        "true" if with_comments else "false",
        "--save_data_option",
        "compat",
        "--max_notes",
        str(max_notes),
    ]
    if headless:
        cmd.extend(["--headless", "true"])
    if cookies:
        cmd.extend(["--lt", "cookie", "--cookies", cookies])
    return cmd


def start_task(task_id, keyword, max_pages):
    """启动爬虫任务（后台运行）"""

    def update_task_status(status, count=0):
        existing = get_task(task_id) or {}
        if existing.get("status") == "stopped":
            return
        payload = {"status": status}
        if status in ("completed", "failed"):
            payload.update(
                {
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "items_count": count,
                    "pid": "",
                }
            )
        update_task(task_id, payload)

    def _run():
        task = get_task(task_id) or {}

        # Clear old logs before starting new task
        log_key = task_log_key(task_id)
        redis_client.delete(log_key)

        try:
            cookie_bundle_name = get_cookie_bundle_name(DEFAULT_COOKIE_BUNDLE_NAME)
            cookie_string = get_cookie_string(DEFAULT_COOKIE_BUNDLE_NAME)
            cmd = _build_crawler_cmd(
                keyword=keyword,
                max_pages=max_pages,
                with_comments=task.get("with_comments", 0),
                cookies=cookie_string,
                headless=True,
            )
            append_task_log(task_id, f"启动任务: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=ROOT_DIR,
                env={
                    **os.environ,
                    "CRAWLER_TASK_ID": str(task_id),
                    "CRAWLER_TASK_SOURCE": "ui",
                    "CRAWLER_COOKIE_BUNDLE_NAME": cookie_bundle_name or "",
                },
                start_new_session=True,
            )
            update_task(
                task_id,
                {
                    "status": "running",
                    "started_at": task.get("started_at")
                    or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "pid": process.pid,
                },
            )

            for line in process.stdout:
                append_task_log(task_id, line.rstrip())

            process.wait()
            count = redis_client.llen(task_data_key(task_id))
            update_task_status("completed" if process.returncode == 0 else "failed", count)
        except Exception as exc:
            append_task_log(task_id, f"任务执行错误: {exc}")
            update_task_status("failed")

    threading.Thread(target=_run, daemon=True).start()


def stop_task(task_id, pid):
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False, "invalid_pid"

    try:
        if os.name != "nt":
            os.killpg(pid_value, signal.SIGTERM)
        else:
            os.kill(pid_value, signal.SIGTERM)
    except ProcessLookupError:
        return False, "not_running"
    except PermissionError:
        return False, "permission_denied"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_task(task_id, {"status": "stopped", "finished_at": now, "pid": ""})
    append_task_log(task_id, "任务已停止")
    return True, None


def start_task_spider(task_id, url, lock_id=None):
    if not TASK_SPIDER_AUTOSTART:
        return {"started": False, "reason": "autostart_disabled"}

    lock_key = f"{TASK_SPIDER_LOCK_PREFIX}{lock_id or task_id}"
    if not redis_client.set(lock_key, "1", nx=True, ex=3600):
        return {"started": False, "reason": "already_running"}

    try:
        log_path = os.path.join(LOG_DIR, f"task_{task_id}.log")
        # Clear old log file by opening in write mode
        log_file = open(log_path, "w", encoding="utf-8")
        keyword = extract_keyword_from_url(url)
        max_pages = int(os.getenv("DEFAULT_MAX_PAGES", str(DEFAULT_PAGE_SIZE)))
        with_comments = os.getenv("MONITOR_DEFAULT_WITH_COMMENTS", "1")
        with_comments_enabled = str(with_comments) in ("1", "true", "True")
        preferred_bundle = MONITOR_COOKIE_BUNDLE_NAME or DEFAULT_COOKIE_BUNDLE_NAME
        cookie_bundle_name = get_cookie_bundle_name(preferred_bundle)
        cookie_string = get_cookie_string(preferred_bundle)
        base_cmd = shlex.split(TASK_SPIDER_CMD)
        cmd = base_cmd + [
            "--keywords",
            str(keyword),
            "--get_comment",
            "true" if with_comments_enabled else "false",
            "--save_data_option",
            "compat",
            "--max_notes",
            str(max_pages * WEIBO_PAGE_SIZE),
            "--headless",
            "true",
        ]
        if cookie_string:
            cmd.extend(["--lt", "cookie", "--cookies", cookie_string])
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=ROOT_DIR,
            env={
                **os.environ,
                "CRAWLER_TASK_ID": str(task_id),
                "CRAWLER_TASK_SOURCE": "monitor",
                "CRAWLER_COOKIE_BUNDLE_NAME": cookie_bundle_name or "",
            },
        )
        app_logger.info("spawn task spider pid=%s cmd=%s", process.pid, " ".join(cmd))

        def _wait():
            returncode = process.wait()
            finalize_task(task_id, returncode)
            redis_client.delete(lock_key)
            app_logger.info("task spider %s exited code=%s", task_id, returncode)

        threading.Thread(target=_wait, daemon=True).start()
        return {"started": True, "pid": process.pid}
    except Exception as exc:
        redis_client.delete(lock_key)
        app_logger.error("spawn task spider failed: %s", exc)
        return {"started": False, "reason": "spawn_failed", "message": str(exc)}


def finalize_task(task_id, returncode):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = redis_client.llen(task_data_key(task_id))
    update_task(
        int(task_id),
        {
            "status": "completed" if returncode == 0 else "failed",
            "finished_at": now,
            "items_count": count,
        },
    )
    append_task_log(task_id, f"任务结束，exit={returncode}，items={count}")


@router.get("/cookies")
async def list_cookies_route():
    return list_cookies()


@router.post("/cookies")
async def add_cookie(request: Request):
    data = await request.json()
    name = data.get("name")
    value = data.get("value")
    if not name or value is None:
        return JSONResponse({"success": False, "error": "invalid_cookie"}, status_code=400)

    existing = get_cookie(name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        payload = {
            "value": value,
            "domain": data.get("domain", existing.get("domain", ".weibo.cn")),
            "path": data.get("path", existing.get("path", "/")),
            "updated_at": now,
        }
    else:
        payload = {
            "name": name,
            "value": value,
            "domain": data.get("domain", ".weibo.cn"),
            "path": data.get("path", "/"),
            "created_at": now,
            "updated_at": now,
        }

    save_cookie(name, payload)
    return {"success": True, "cookies": list_cookies()}


@router.delete("/cookies")
async def delete_cookie_route(name: str):
    if name:
        delete_cookie(name)
    return {"success": True, "cookies": list_cookies()}


@router.get("/cookie_bundles")
async def list_cookie_bundles_route():
    return list_cookie_bundles()


@router.post("/cookie_bundles")
async def add_cookie_bundle(request: Request):
    data = await request.json()
    name = data.get("name")
    cookie_string = data.get("cookie_string")
    proxies = data.get("proxies", [])
    user_agent = data.get("user_agent", "")
    if not name or not cookie_string:
        return JSONResponse({"success": False, "error": "invalid_payload"}, status_code=400)
    save_cookie_bundle(name, cookie_string, proxies, user_agent)
    return {"success": True, "bundles": list_cookie_bundles()}


@router.delete("/cookie_bundles")
async def delete_cookie_bundle_route(name: str):
    if name:
        delete_cookie_bundle(name)
    return {"success": True, "bundles": list_cookie_bundles()}


@router.post("/cookie_bundles/{name}/validate")
async def validate_cookie_bundle(name: str):
    bundle = get_cookie_bundle(name)
    if not bundle:
        return JSONResponse({"success": False, "error": "not_found"}, status_code=404)
    ok, status = _validate_cookie_string(
        bundle.get("cookie_string", ""), bundle.get("user_agent", "")
    )
    if ok:
        _update_cookie_bundle_status(name, True, "ok")
    elif status == "expired":
        _update_cookie_bundle_status(name, False, "expired")
    else:
        _update_cookie_bundle_status(name, True, "error", status)
    return {"success": True, "name": name, "valid": ok, "status": status}


@router.post("/cookie_bundles/validate_all")
async def validate_all_cookie_bundles():
    results = []
    for bundle in list_cookie_bundles():
        name = bundle.get("name")
        ok, status = _validate_cookie_string(
            bundle.get("cookie_string", ""), bundle.get("user_agent", "")
        )
        if ok:
            _update_cookie_bundle_status(name, True, "ok")
        elif status == "expired":
            _update_cookie_bundle_status(name, False, "expired")
        else:
            _update_cookie_bundle_status(name, True, "error", status)
        results.append({"name": name, "valid": ok, "status": status})
    return {"success": True, "results": results}




@router.get("/proxies")
async def list_proxies_route():
    return list_proxies()


@router.post("/proxies")
async def add_proxy_route(request: Request):
    data = await request.json()
    proxy = (data.get("proxy") or "").strip()
    proxies = data.get("proxies")
    if not proxy and not proxies:
        return JSONResponse({"success": False, "error": "invalid_payload"}, status_code=400)
    if proxies:
        add_proxies(proxies)
    else:
        add_proxy(proxy)
    return {"success": True, "proxies": list_proxies()}


@router.delete("/proxies")
async def delete_proxy_route(proxy: str):
    proxy = (proxy or "").strip()
    if proxy:
        delete_proxy(proxy)
    return {"success": True, "proxies": list_proxies()}


@router.get("/tasks")
async def list_tasks():
    ids = redis_client.lrange(TASK_INDEX_LIST, 0, -1)
    tasks = []
    for task_id in ids:
        task = get_task(task_id)
        if task:
            tasks.append(_refresh_task_status(task))
    return tasks


@router.get("/processes")
async def list_task_processes():
    ids = redis_client.lrange(TASK_INDEX_LIST, 0, -1)
    tasks = []
    task_by_pid = {}
    task_by_keyword = {}
    for task_id in ids:
        task = get_task(task_id)
        if not task:
            continue
        task = _refresh_task_status(task)
        tasks.append(task)
        if task.get("pid"):
            task_by_pid[str(task.get("pid"))] = task
        keyword = (task.get("keyword") or "").strip()
        if keyword:
            task_by_keyword[keyword] = task

    processes = []
    for proc in _list_crawler_processes():
        task = task_by_pid.get(proc.get("pid"))
        if not task and proc.get("keyword"):
            task = task_by_keyword.get(proc.get("keyword"))
        processes.append(
            {
                "task_id": task.get("id") if task else None,
                "keyword": task.get("keyword") if task else proc.get("keyword"),
                "status": task.get("status") if task else "running",
                "started_at": task.get("started_at") if task else "",
                "pid": proc.get("pid"),
                "process": {
                    "pid": proc.get("pid"),
                    "ppid": proc.get("ppid"),
                    "pgid": proc.get("pgid"),
                    "etime": proc.get("etime"),
                    "command": proc.get("command"),
                },
            }
        )
    return processes


@router.post("/tasks")
async def create_task(request: Request):
    data = await request.json()
    task_id = redis_client.incr(TASK_ID_KEY)
    new_task = {
        "id": task_id,
        "keyword": data.get("keyword", "Python"),
        "max_pages": data.get("max_pages", DEFAULT_PAGE_SIZE),
        "with_comments": 1 if data.get("with_comments") else 0,
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": "",
        "finished_at": "",
        "items_count": 0,
        "output_file": "",
        "data_key": task_data_key(task_id),
    }

    save_task(new_task)
    start_task(new_task["id"], new_task["keyword"], new_task["max_pages"])
    return {"success": True, "task": new_task}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    redis_client.delete(task_key(task_id))
    redis_client.lrem(TASK_INDEX_LIST, 0, str(task_id))
    redis_client.srem(TASK_INDEX_SET, str(task_id))
    return {"success": True}


@router.post("/tasks/{task_id}/start")
async def start_task_route(task_id: int):
    task = get_task(task_id)
    if task and task["status"] != "running":
        update_task(
            task_id,
            {
                "status": "running",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        start_task(task_id, task["keyword"], task["max_pages"])

    return {"success": True}


@router.post("/tasks/{task_id}/stop")
async def stop_task_route(task_id: int):
    task = get_task(task_id)
    if not task:
        return JSONResponse({"success": False, "error": "task_not_found"}, status_code=404)
    if task.get("status") != "running":
        return JSONResponse({"success": False, "error": "not_running"}, status_code=400)
    ok, reason = stop_task(task_id, task.get("pid"))
    if not ok:
        return JSONResponse({"success": False, "error": reason}, status_code=400)
    return {"success": True}


@router.get("/data/{filename}")
async def download_file(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "file_not_found"}, status_code=404)
    return FileResponse(path, filename=filename)


@router.get("/data/{filename}/preview")
async def preview_file(filename: str, limit: int = 50):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "file_not_found"}, status_code=404)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    if isinstance(data, list):
        preview = data[: max(0, limit)]
        return {"total": len(data), "items": preview}
    return {"total": 1, "items": [data]}


@router.get("/tasks/{task_id}/logs")
async def task_logs(task_id: int, limit: int = 200):
    file_path = os.path.join(LOG_DIR, f"task_{task_id}.log")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            total = len(lines)
            if total > 0:
                start = max(0, total - max(0, limit))
                return {"total": total, "lines": [l.rstrip() for l in lines[start:]]}
        except Exception:
            pass
    key = task_log_key(task_id)
    total = redis_client.llen(key)
    if total == 0:
        return {"total": 0, "lines": []}

    start = max(0, total - max(0, limit))
    lines = redis_client.lrange(key, start, total - 1)
    return {"total": total, "lines": lines}


@router.get("/tasks/{task_id}/stats")
async def task_stats(task_id: int):
    task = get_task(task_id)
    duration_seconds = 0
    if task and task.get("started_at"):
        try:
            started = datetime.strptime(task.get("started_at"), "%Y-%m-%d %H:%M:%S")
            finished_at = task.get("finished_at") or ""
            if finished_at:
                finished = datetime.strptime(finished_at, "%Y-%m-%d %H:%M:%S")
                duration_seconds = max(0, int((finished - started).total_seconds()))
            else:
                duration_seconds = max(0, int((datetime.now() - started).total_seconds()))
        except Exception:
            duration_seconds = 0
    data = redis_client.hgetall(task_stats_key(task_id))
    if not data:
        return {
            "pages_crawled": 0,
            "content_inserted": 0,
            "content_updated": 0,
            "comment_inserted": 0,
            "comment_updated": 0,
            "duration_seconds": duration_seconds,
            "search_seconds": 0,
            "full_text_seconds": 0,
            "comments_seconds": 0,
            "sleep_seconds": 0,
        }
    return {
        "pages_crawled": int(data.get("pages_crawled", 0)),
        "content_inserted": int(data.get("content_inserted", 0)),
        "content_updated": int(data.get("content_updated", 0)),
        "comment_inserted": int(data.get("comment_inserted", 0)),
        "comment_updated": int(data.get("comment_updated", 0)),
        "duration_seconds": duration_seconds,
        "search_seconds": float(data.get("search_seconds", 0)),
        "full_text_seconds": float(data.get("full_text_seconds", 0)),
        "comments_seconds": float(data.get("comments_seconds", 0)),
        "sleep_seconds": float(data.get("sleep_seconds", 0)),
    }


@router.get("/tasks/{task_id}/data")
async def task_data(task_id: int, limit: int = 50, offset: int = 0):
    key = task_data_key(task_id)
    total = redis_client.llen(key)
    if total == 0:
        return {"total": 0, "items": []}

    start = max(0, offset)
    end = min(total - 1, start + max(0, limit) - 1)
    raw = redis_client.lrange(key, start, end)
    items = []
    for line in raw:
        try:
            items.append(json.loads(line))
        except Exception:
            items.append({"raw": line})
    return {"total": total, "items": items}


@router.get("/tasks/{task_id}/comments")
async def task_comments(task_id: int, limit: int = 50, offset: int = 0):
    key = f"{os.getenv('REDIS_TASK_COMMENTS_PREFIX', 'weibo:task:comments:')}{task_id}"
    total = redis_client.llen(key)
    if total == 0:
        return {"total": 0, "items": []}

    start = max(0, offset)
    end = min(total - 1, start + max(0, limit) - 1)
    raw = redis_client.lrange(key, start, end)
    items = []
    for line in raw:
        try:
            items.append(json.loads(line))
        except Exception:
            items.append({"raw": line})
    return {"total": total, "items": items}


@router.get("/sentiment/words")
async def list_sentiment_word_group(word_type: str = ""):
    mapping = {
        "positive": "positive",
        "negative": "negative",
        "negation": "negation",
        "degree": "degree",
        "stopwords": "stopwords",
    }

    if word_type:
        if word_type not in mapping:
            return JSONResponse({"error": "invalid_type"}, status_code=400)
        return list_sentiment_words(word_type)

    data = {key: list_sentiment_words(key) for key in mapping}
    return data


@router.post("/sentiment/words")
async def add_sentiment(request: Request):
    data = await request.json()
    word_type = data.get("type")
    word = (data.get("word") or "").strip()
    words = data.get("words")
    if not word_type or (not word and not words):
        return JSONResponse({"error": "invalid_payload"}, status_code=400)
    if word_type not in ("positive", "negative", "negation", "degree", "stopwords"):
        return JSONResponse({"error": "invalid_type"}, status_code=400)
    if words:
        add_sentiment_words(word_type, words)
    else:
        add_sentiment_word(word_type, word)
    return {"success": True}


@router.delete("/sentiment/words")
async def delete_sentiment(word_type: str, word: str):
    if not word_type or not word:
        return JSONResponse({"error": "invalid_payload"}, status_code=400)
    if word_type not in ("positive", "negative", "negation", "degree", "stopwords"):
        return JSONResponse({"error": "invalid_type"}, status_code=400)
    remove_sentiment_word(word_type, word)
    return {"success": True}


@router.get("/monitor/tasks")
async def list_monitor_tasks(
    ms_types: str = "11", page: int = 1, page_size: int = 50, keyword: str = ""
):
    if not monitor_engine:
        app_logger.warning("monitor mysql disabled")
        return JSONResponse({"error": "monitor_mysql_disabled"}, status_code=400)

    ms_type_list = ms_types.split(",")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    offset = (page - 1) * page_size

    keyword = (keyword or "").strip()
    where_clause = "where ms_type in :types"
    if keyword:
        where_clause += " and (ms_keys like :kw or ms_start_url like :kw)"

    sql = text(
        f"""
        select ms_id, ms_type, ms_keys, ms_start_url, ms_status, ms_remark,
               ms_create_date, ms_modify_date, valid_start_date, valid_end_date,
               industry, institution_name
        from web_monitorspider
        {where_clause}
        order by ms_modify_date desc
        limit :limit offset :offset
        """
    )
    count_sql = text(
        f"select count(*) as total from web_monitorspider {where_clause}"
    )

    try:
        params = {"types": tuple(ms_type_list), "limit": page_size, "offset": offset}
        if keyword:
            params["kw"] = f"%{keyword}%"
        with monitor_engine.connect() as conn:
            total = conn.execute(count_sql, params).scalar() or 0
            rows = conn.execute(sql, params).mappings()
            tasks = [dict(row) for row in rows]
    except Exception as exc:
        app_logger.error("monitor mysql query failed: %s", exc)
        return JSONResponse(
            {"error": "monitor_mysql_unavailable", "message": str(exc)}, status_code=500
        )

    return {"total": total, "page": page, "page_size": page_size, "tasks": tasks}


@router.post("/monitor/tasks/{ms_id}/enqueue")
async def enqueue_monitor_task(ms_id: int):
    if not monitor_engine:
        app_logger.warning("monitor mysql disabled")
        return JSONResponse({"error": "monitor_mysql_disabled"}, status_code=400)

    sql = text(
        """
        select ms_id, ms_type, ms_keys, ms_start_url
        from web_monitorspider
        where ms_id = :ms_id
        """
    )
    try:
        with monitor_engine.connect() as conn:
            row = conn.execute(sql, {"ms_id": ms_id}).mappings().first()
            if not row:
                return JSONResponse({"error": "task_not_found"}, status_code=404)
    except Exception as exc:
        app_logger.error("monitor mysql query failed: %s", exc)
        return JSONResponse(
            {"error": "monitor_mysql_unavailable", "message": str(exc)}, status_code=500
        )

    url = row.get("ms_start_url") or ""
    if not url and row.get("ms_keys"):
        keyword = row["ms_keys"]
        url = (
            "https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D1%26q="
            + keyword
            + "&page_type=searchall"
        )
    if not url:
        return JSONResponse({"error": "empty_start_url"}, status_code=400)

    task_id = redis_client.incr(TASK_ID_KEY)
    keyword = row.get("ms_keys") or extract_keyword_from_url(url) or ""
    new_task = {
        "id": task_id,
        "keyword": keyword,
        "max_pages": int(os.getenv("DEFAULT_MAX_PAGES", str(DEFAULT_PAGE_SIZE))),
        "with_comments": 1 if os.getenv("MONITOR_DEFAULT_WITH_COMMENTS", "1") in ("1", "true", "True") else 0,
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": "",
        "finished_at": "",
        "items_count": 0,
        "output_file": "",
        "data_key": task_data_key(task_id),
        "monitor_id": ms_id,
        "source": "monitor",
    }
    save_task(new_task)

    redis_key = os.getenv("MONITOR_REDIS_KEY", "weibo_spider:start_urls")
    redis_client.lpush(redis_key, url)
    app_logger.info("enqueue monitor task %s -> %s (task_id=%s)", ms_id, url, task_id)
    start_info = start_task_spider(task_id, url, lock_id=ms_id)
    task_status = "running" if start_info.get("started") else "pending"
    update_task(
        task_id,
        {
            "status": task_status,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if task_status == "running"
            else "",
        },
    )
    append_task_log(task_id, f"已加入队列: {url}")
    if start_info.get("started"):
        append_task_log(task_id, "爬虫已启动")
    elif start_info.get("reason") == "already_running":
        append_task_log(task_id, "爬虫已在运行")
    return {"success": True, "queued": url, "spider": start_info, "task_id": task_id}


@router.get("/logs")
async def read_logs(limit: int = 200):
    if not os.path.exists(LOG_FILE):
        return {"total": 0, "lines": []}
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {"total": 0, "lines": []}
    total = len(lines)
    start = max(0, total - max(0, limit))
    return {"total": total, "lines": [l.rstrip() for l in lines[start:]]}
