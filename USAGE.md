# 使用指南

本文面向首次使用本仓库的开发者，覆盖环境准备、运行方式、平台示例与常见配置入口。

## 1. 环境准备
- Python 版本：>= 3.11
- Node.js：>= 16（爬取抖音/知乎时需要）
- 推荐使用 `uv` 管理依赖

```sh
uv sync
uv run playwright install
```

## 2. 运行爬虫（CLI）
常用入口为 `main.py`，参数说明可用 `--help` 查看。

```sh
uv run main.py --help
```

### 平台示例（小红书）
关键词搜索与详情抓取示例：
```sh
uv run main.py --platform xhs --lt qrcode --type search
uv run main.py --platform xhs --lt qrcode --type detail
```
运行后按提示扫码登录。其他平台的参数用法可按 `--help` 查看，并在 `config/base_config.py` 中配置关键字、指定 ID 列表与是否抓取评论等选项。

### 其他平台提示
抖音、知乎等平台依赖 Node.js 环境，请先安装并确保版本满足要求。具体平台支持情况与参数含义请参考项目 README 与配置文件注释。

## 3. WebUI 模式
启动 WebUI 服务（默认端口 8080）：
```sh
uv run uvicorn api.main:app --port 8080 --reload
```
然后访问：`http://localhost:8080`

## 4. 数据保存
支持 CSV、JSON、Excel、SQLite、MySQL 等方式。详细配置与用法请阅读：
`docs/data_storage_guide.md`

## 5. 不使用 uv 的安装方式（可选）
```sh
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install
python main.py --platform xhs --lt qrcode --type search
```

## 6. 常见问题
- 登录方式与抓取范围：请优先查看 `config/base_config.py` 的中文注释。
- 浏览器驱动缺失：确保执行过 `playwright install`。
