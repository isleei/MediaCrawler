# 舆情系统爬虫

## 简介

本项目基于 MediaCrawler 二次修改，用于舆情系统的数据采集与分析场景。

## 安装/运行

推荐使用 uv：
```
uv sync
uv run playwright install
```

运行爬虫示例：
```
uv run python main.py --platform wb --type search --keywords 洛杉矶 --get_comment true
```

运行 WebUI：
```
uv run uvicorn api.main:app --port 8080 --reload
```

访问地址：
```
http://<服务器IP>:8080/weibo
```

## 环境变量示例

在项目根目录创建 `.env`：
```
MYSQL_DB_HOST=127.0.0.1
MYSQL_DB_PORT=3306
MYSQL_DB_USER=root
MYSQL_DB_PWD=123456
MYSQL_DB_NAME=media_crawler

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=

ES_HOSTS=http://127.0.0.1:9200
ES_ENABLED=1

MAX_CONCURRENT_TASKS=1
```

## ES-only 模式

如需仅写入 ES，不写 MySQL：
```
SAVE_DATA_OPTION=compat
WEIBO_MYSQL_ENABLED=0
WEIBO_CONTENT_MYSQL_ENABLED=0
WEIBO_COMMENT_MYSQL_ENABLED=0
```

## 任务队列说明

- WebUI 通过队列控制任务并发（默认 1）。
- 任务日志写入 `logs/tasks/task_<id>.log`，UI 重启不影响已启动任务。

## 配置注意事项

- MySQL 字符集必须是 `utf8mb4`，否则包含 emoji 会写入失败。
- Docker 内置 Playwright 时，建议 `ENABLE_CDP_MODE=false`。
- 单任务并发受 `MAX_CONCURRENCY_NUM` 影响，WebUI 并发受 `MAX_CONCURRENT_TASKS` 影响。
- 评论开关：
  - 命令行 `--get_comment true/false`
  - 全局 `ENABLE_GET_COMMENTS`（`config/base_config.py`）
- 评论未变化跳过：
  - `WEIBO_SKIP_COMMENTS_IF_UNCHANGED=1`（依赖 ES）
- Cookie 自动重试：
  - `ENABLE_COOKIE_RETRY=1`，仅微博接口相关错误会触发禁用/重试。
- 线上部署建议关闭 `--reload`，避免频繁重启导致资源抖动。

## 常见问题

- WebUI 停止/重启后爬虫任务是否会停止？
  - 任务日志写入 `logs/tasks/task_<id>.log`，UI 重启不会影响已启动的任务。
- 写入 MySQL 报错 `Incorrect string value`？
  - 确保数据库与表使用 `utf8mb4` 字符集。

## Docker

参考文档：
- docs/DOCKER部署指南.md
