MediaCrawler Docker 部署指南

目标: WebUI + 爬虫，内置 Playwright 浏览器。

前置
- Docker >= 20
- docker-compose >= 1.29 或 Docker Compose v2

1) 构建并启动
```
docker compose up -d --build
```

2) 访问 WebUI
```
http://<服务器IP>:8080/weibo
```

3) 环境变量
在项目根目录创建 `.env`（不提交），示例:
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

4) 说明
- 容器内已安装 Playwright 浏览器及依赖。
- 默认关闭 CDP 模式（容器内不依赖宿主机 Chrome）。
- 任务日志在 `logs/tasks/task_<id>.log`。

5) 常用命令
```
docker compose logs -f mediacrawler
docker compose restart mediacrawler
docker compose down
```
