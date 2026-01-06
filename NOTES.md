# 沟通记录（MediaCrawler 替代方案）

## 目标
- 新建一个处理项目，负责情感分析、关键词等后处理。
- MediaCrawler 只负责爬虫与原始数据输出。

## 当前结论
- MediaCrawler 可作为“纯爬虫层”，通过 CLI/WebUI API 启动任务。
- WebUI/API 目前仅支持启动/停止任务与配置选择，不支持对外数据推送接口。
- 多账号并发分流尚未实现，需额外开发（账号池、调度、上下文隔离等）。
- Linux 无桌面环境无法扫码登录，建议 Cookie 或手机号验证码登录。
- 代理池配置在 `config/base_config.py`：
  `ENABLE_IP_PROXY`、`IP_PROXY_POOL_COUNT`、`IP_PROXY_PROVIDER_NAME`。

## 待确认事项
- 对接方式：
  - A：MediaCrawler 写数据库，新项目消费处理；
  - B：MediaCrawler 抓取后 HTTP 推送（需新增 webhook）。
- 数据输出字段：内容ID、正文、作者、时间、链接、互动数等具体需求。
- 数据库类型与表结构：MySQL/SQLite/Mongo，是否需兼容既有表结构。
- 触发方式：后台调用 `/api/crawler/start` 是否足够，或需要更复杂调度。

## 后续可选增强
- 如果需要断点/进度存储，可在新项目维护游标或在 MediaCrawler 内部新增进度表/文件。
