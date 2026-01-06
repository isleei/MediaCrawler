# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MediaCrawler 是一个多平台自媒体数据采集工具，支持小红书、抖音、快手、B站、微博、贴吧、知乎等平台的公开信息抓取。项目基于 Playwright 浏览器自动化框架，通过保留登录态的方式避免复杂的 JS 逆向工程。

**重要提示**：本项目仅供学习和研究使用，禁止用于商业用途或大规模爬取。

## 开发环境设置

### 依赖管理

项目使用 **uv** 作为包管理工具（推荐）：

```bash
# 安装依赖并同步环境
uv sync

# 安装 Playwright 浏览器驱动
uv run playwright install
```

传统方式（不推荐）：
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
playwright install
```

### Python 版本要求

- Python >= 3.11
- Node.js >= 16.0.0（抖音和知乎平台需要）

## 常用命令

### 运行爬虫

```bash
# 基本命令格式
uv run main.py --platform <平台> --lt <登录方式> --type <爬取类型>

# 示例：小红书关键词搜索（二维码登录）
uv run main.py --platform xhs --lt qrcode --type search

# 示例：抖音指定帖子爬取
uv run main.py --platform xhs --lt qrcode --type detail

# 查看所有可用选项
uv run main.py --help
```

**平台代码**：
- `xhs` - 小红书
- `dy` - 抖音
- `ks` - 快手
- `bili` - 哔哩哔哩
- `wb` - 微博
- `tieba` - 百度贴吧
- `zhihu` - 知乎

**登录方式**：
- `qrcode` - 二维码登录
- `phone` - 手机号登录
- `cookie` - Cookie 登录

**爬取类型**：
- `search` - 关键词搜索
- `detail` - 指定帖子详情
- `creator` - 创作者主页数据

### WebUI 服务

```bash
# 启动 WebUI API 服务器（默认端口 8080）
uv run uvicorn api.main:app --port 8080 --reload

# 或使用模块方式启动
uv run python -m api.main
```

访问 `http://localhost:8080` 打开 WebUI 界面。

### 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试文件
uv run pytest tests/test_excel_store.py

# 运行带详细输出的测试
uv run pytest -v

# 运行异步测试
uv run pytest -v tests/test_excel_store.py -k "test_store_content"
```

### 数据库初始化

```bash
# 初始化 MySQL 数据库
uv run main.py --init_db mysql

# 初始化 SQLite 数据库
uv run main.py --init_db sqlite
```

## 项目架构

### 核心设计模式

项目采用**模块化多平台爬虫架构**，通过抽象基类和工厂模式实现统一管理：

1. **工厂模式**：`CrawlerFactory` 根据平台类型创建对应爬虫实例（main.py:50-67）
2. **抽象基类**：定义统一接口（`AbstractCrawler`、`AbstractStore`、`AbstractLogin`）
3. **策略模式**：不同平台实现各自的爬取策略

### 目录结构

```
MediaCrawler/
├── base/                    # 抽象基类层
│   └── base_crawler.py     # 定义 AbstractCrawler、AbstractLogin、AbstractStore 等核心接口
├── media_platform/          # 平台实现层
│   ├── xhs/                # 小红书实现
│   │   ├── core.py        # 主爬虫逻辑
│   │   ├── client.py      # API 客户端
│   │   ├── login.py       # 登录逻辑
│   │   ├── field.py       # 数据字段定义
│   │   └── _store_impl.py # 存储实现
│   ├── douyin/            # 抖音实现
│   ├── kuaishou/          # 快手实现
│   ├── bilibili/          # B站实现
│   ├── weibo/             # 微博实现
│   ├── tieba/             # 贴吧实现
│   └── zhihu/             # 知乎实现
├── store/                  # 数据存储层
│   ├── csv_store_base.py  # CSV 存储基类
│   ├── excel_store_base.py # Excel 存储基类
│   └── mongodb_store_base.py # MongoDB 存储基类
├── database/               # 数据库层
│   ├── models.py          # 所有平台的数据库模型
│   ├── db.py              # 数据库连接管理
│   └── db_session.py      # 会话管理
├── tools/                  # 工具层
│   ├── browser_launcher.py # 浏览器启动管理
│   ├── cdp_browser.py     # Chrome DevTools Protocol 支持
│   ├── async_file_writer.py # 异步文件写入
│   └── crawler_util.py    # 爬虫工具函数
├── config/                 # 配置文件
│   ├── base_config.py     # 基础配置（重要：包含所有功能开关）
│   ├── xhs_config.py      # 小红书配置
│   ├── dy_config.py       # 抖音配置
│   └── ...                # 其他平台配置
├── api/                    # WebUI API 服务
│   ├── main.py            # FastAPI 应用入口
│   ├── routers/           # API 路由
│   ├── schemas/           # 数据模型
│   └── services/          # 业务逻辑
└── tests/                  # 测试文件
    ├── test_excel_store.py
    └── test_store_factory.py
```

### 数据流向

```
1. 启动 → CrawlerFactory.create_crawler() → 平台 Crawler 实例
2. 登录 → Login.begin() → 选择登录方式（二维码/手机/Cookie）
3. 爬取 → Crawler.search() → Client.request() → 平台 API → 数据提取
4. 处理 → 原始数据 → Extractor 提取 → 数据模型转换 → 数据清洗
5. 存储 → Store.store_content/store_comment/store_creator → 多种存储方式
```

### 关键抽象接口

所有平台爬虫必须实现以下接口（定义在 `base/base_crawler.py`）：

```python
# AbstractCrawler - 爬虫核心接口
async def start()           # 启动爬虫
async def search()          # 搜索功能
async def launch_browser()  # 浏览器启动

# AbstractStore - 存储接口
async def store_content(content_item: Dict)  # 存储内容
async def store_comment(comment_item: Dict)  # 存储评论
async def store_creator(creator: Dict)       # 存储创作者信息
```

## 配置管理

### 主配置文件

所有功能配置都在 `config/base_config.py` 中，包括：

- `PLATFORM`：目标平台（xhs/dy/ks/bili/wb/tieba/zhihu）
- `KEYWORDS`：搜索关键词（逗号分隔）
- `LOGIN_TYPE`：登录方式（qrcode/phone/cookie）
- `CRAWLER_TYPE`：爬取类型（search/detail/creator）
- `ENABLE_IP_PROXY`：是否启用 IP 代理
- `HEADLESS`：是否使用无头浏览器
- `SAVE_DATA_OPTION`：数据保存方式（csv/db/json/sqlite/excel/mongodb）
- `ENABLE_GET_COMMENTS`：是否爬取评论（默认开启）
- `ENABLE_GET_SUB_COMMENTS`：是否爬取二级评论（默认关闭）
- `ENABLE_GET_MEIDAS`：是否下载媒体资源（默认关闭）
- `ENABLE_GET_WORDCLOUD`：是否生成评论词云图（默认关闭）
- `CRAWLER_MAX_NOTES_COUNT`：爬取帖子数量限制
- `MAX_CONCURRENCY_NUM`：并发爬虫数量

### CDP 模式配置

项目支持 Chrome DevTools Protocol 模式，使用用户现有浏览器：

- `ENABLE_CDP_MODE`：是否启用 CDP 模式（默认 True）
- `CDP_DEBUG_PORT`：CDP 调试端口（默认 9222）
- `CUSTOM_BROWSER_PATH`：自定义浏览器路径（可选）
- `AUTO_CLOSE_BROWSER`：程序结束时是否关闭浏览器

## 添加新平台支持

要添加新平台，需要实现以下文件：

1. `media_platform/<platform>/core.py` - 继承 `AbstractCrawler`
2. `media_platform/<platform>/client.py` - 继承 `AbstractApiClient`
3. `media_platform/<platform>/login.py` - 继承 `AbstractLogin`
4. `media_platform/<platform>/_store_impl.py` - 继承 `AbstractStore`
5. `config/<platform>_config.py` - 平台特定配置
6. 在 `main.py` 的 `CrawlerFactory.CRAWLERS` 字典中注册新平台

## 数据存储

项目支持多种存储方式（通过 `SAVE_DATA_OPTION` 配置）：

- **JSON**：异步写入 JSON 文件（`tools/async_file_writer.py`）
- **CSV**：CSV 文件存储
- **Excel**：Excel 文件存储（使用单例模式，`store/excel_store_base.py`）
- **SQLite**：SQLite 数据库（通过 SQLAlchemy ORM）
- **MySQL**：MySQL 数据库（需配置 `config/db_config.py`）
- **MongoDB**：MongoDB 数据库（`database/mongodb_store_base.py`）

数据库模型定义在 `database/models.py`（453 行，包含所有平台的表结构）。

### MySQL 密码特殊字符处理

**重要**：如果 MySQL 密码包含特殊字符（如 `@`、`#`、`$`、`%`），项目使用了自定义的连接方式来避免 SQLAlchemy URL 解析问题。

相关文件：
- `database/db_utils.py` - 提供 `create_mysql_engine_safe()` 和 `create_mysql_engine_from_env()` 工具函数
- 使用自定义 `creator` 函数直接调用 `pymysql.connect()`，绕过 URL 编码问题

如果需要添加新的 MySQL 连接，请使用 `database/db_utils.py` 中的工具函数，而不是直接使用 `create_engine()` 和 URL 字符串。

## 技术特色

### 浏览器控制
- 使用 Playwright 进行浏览器自动化
- 支持 CDP 模式使用用户现有浏览器，降低被检测风险
- 支持无头模式和有头模式

### 异步架构
- 全面使用 asyncio 实现异步处理
- 通过 `ContextVar` 管理并发任务状态（`var.py`）
- 数据库连接池管理

### 代理支持
- 支持多种代理提供商（kuaidaili、wandouhttp）
- 代理 IP 池管理（`proxy/` 目录）
- 自动代理轮换

## 注意事项

1. **反爬虫处理**：每个平台都有专门的签名算法和反爬虫策略，修改时需注意
2. **登录态保存**：浏览器上下文保存在 `<platform>_user_data_dir/` 目录
3. **并发控制**：通过 `MAX_CONCURRENCY_NUM` 控制并发数，避免触发平台限制
4. **数据去重**：使用数据库存储时有去重功能，JSON/CSV 需手动处理
5. **Excel 存储**：使用单例模式，程序结束时调用 `ExcelStoreBase.flush_all()` 保存
6. **二级评论**：如果使用旧版数据库，需参考 `schema/tables.sql` line 287 增加表字段

## 调试技巧

1. **查看浏览器操作**：设置 `HEADLESS = False` 打开浏览器窗口
2. **登录问题**：小红书扫码不通过时，手动过滑动验证码；抖音出现手机号验证时手动处理
3. **CDP 端口占用**：系统会自动尝试下一个可用端口
4. **日志输出**：项目使用标准 logging 模块，可调整日志级别查看详细信息
