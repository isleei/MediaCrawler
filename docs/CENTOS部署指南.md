MediaCrawler CentOS 部署指南

本指南以 CentOS 7/8 为例，给出最小可用的部署步骤。按需选用 MySQL/Redis/ES。

前置要求
- 服务器可访问目标平台
- Python >= 3.11
- Git
- Chrome/Chromium 可用（CDP 模式需要）

1) 系统依赖

CentOS 7:
```
sudo yum -y install epel-release
sudo yum -y groupinstall "Development Tools"
sudo yum -y install git curl wget unzip \
  openssl-devel bzip2-devel libffi-devel zlib-devel \
  sqlite-devel xz-devel
```

CentOS 8:
```
sudo dnf -y groupinstall "Development Tools"
sudo dnf -y install git curl wget unzip \
  openssl-devel bzip2-devel libffi-devel zlib-devel \
  sqlite-devel xz-devel
```

2) 安装 Python 3.11

建议用 pyenv 或源码编译。

源码编译示例:
```
cd /usr/local/src
sudo wget https://www.python.org/ftp/python/3.11.10/Python-3.11.10.tgz
sudo tar xzf Python-3.11.10.tgz
cd Python-3.11.10
sudo ./configure --enable-optimizations
sudo make -j$(nproc)
sudo make altinstall
python3.11 -V
```

3) 安装 uv
```
curl -Ls https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv -V
```

4) 拉取项目
```
git clone https://github.com/NanmiCoder/MediaCrawler.git
cd MediaCrawler
```

5) 安装依赖
```
uv sync
uv run playwright install
```

如果 Playwright 依赖缺失（浏览器启动失败），安装系统库:
- CentOS 7/8 上依赖可能不同，建议直接运行:
```
uv run playwright install --with-deps
```

6) 配置 .env
创建 `.env`（不要提交到仓库），按需配置:
```
MYSQL_DB_HOST=127.0.0.1
MYSQL_DB_PORT=3306
MYSQL_DB_USER=root
MYSQL_DB_PWD=123456
MYSQL_DB_NAME=media_crawler

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=

# ES
ES_HOSTS=http://127.0.0.1:9200
ES_ENABLED=1

# WebUI 任务并发
MAX_CONCURRENT_TASKS=1
```

7) 运行爬虫（CLI）
```
uv run python main.py --platform wb --type search --keywords 洛杉矶 --get_comment true
```

8) 运行 WebUI
```
uv run uvicorn api.main:app --port 8080 --reload
```

访问:
```
http://<服务器IP>:8080/weibo
```

9) CDP 模式与浏览器

默认开启 CDP 模式（`config/base_config.py` 的 `ENABLE_CDP_MODE=True`）。
- 服务器若无 GUI，可考虑关闭 CDP 或使用无头模式。
- 如需指定 Chrome 路径，可配置:
```
CUSTOM_BROWSER_PATH=/usr/bin/google-chrome
```

10) 常见问题

- 数据库字符集导致写入失败:
  - 请确保 MySQL 库/表为 `utf8mb4`。
- 端口无法访问:
  - 开放防火墙端口（如 8080）。
- 爬虫日志:
  - UI 启动的任务日志在 `logs/tasks/task_<id>.log`。

11) systemd（可选）

WebUI 示例服务:
```
[Unit]
Description=MediaCrawler WebUI
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/MediaCrawler
ExecStart=/usr/bin/env bash -lc 'uv run uvicorn api.main:app --host 0.0.0.0 --port 8080'
Restart=on-failure
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin

[Install]
WantedBy=multi-user.target
```

启用:
```
sudo systemctl daemon-reload
sudo systemctl enable mediacrawler-webui
sudo systemctl start mediacrawler-webui
```
