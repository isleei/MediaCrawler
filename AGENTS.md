# Repository Guidelines

## 项目结构与模块组织
核心代码位于仓库根目录及若干子模块：`main.py` 为 CLI 入口；`api/` 提供 WebUI 与 FastAPI 服务；`media_platform/` 与 `base/` 聚合平台抓取逻辑与基础能力；`config/` 保存配置项与默认参数；`store/`、`database/` 负责数据落库与导出；`proxy/`、`cache/`、`libs/` 为网络与通用工具层。文档与静态资源在 `docs/`，单元测试在 `tests/`，集成/功能测试在 `test/`。

## 构建、测试与本地运行
推荐使用 `uv` 管理依赖与运行：
```sh
uv sync
uv run playwright install
uv run main.py --platform xhs --lt qrcode --type search
```
WebUI 启动：
```sh
uv run uvicorn api.main:app --port 8080 --reload
```
文档站点（可选，需 Node.js >=16）：
```sh
npm run docs:dev
```
若不用 uv，可使用 `python -m venv venv` + `pip install -r requirements.txt`。

## 编码风格与命名
Python 版本要求 `>=3.11`。遵循 PEP 8：4 空格缩进、`snake_case` 函数与变量、`PascalCase` 类名、常量用 `UPPER_CASE`。配置改动集中在 `config/`，避免硬编码散落。若新增模块，请与现有目录责任对齐。

## 测试指南
`tests/` 采用 `pytest`/`pytest-asyncio`；`test/` 中含 `unittest` 与集成测试。常用命令：
```sh
pytest
python test/test_mongodb_integration.py
```
涉及 MongoDB/Redis 的测试需要本地服务可用，请在提交前注明依赖。

## 提交与 PR 指南
历史提交采用 Conventional Commits 风格，如 `feat(api): ...`、`fix: ...`、`docs: ...`。PR 请说明变更动机、影响范围与验证方式；如涉及 WebUI/文档，附截图或预览命令输出。

## 配置与安全提示
抓取参数与登录方式集中在 `config/base_config.py`。使用代理或数据库账号时，优先通过环境变量或本地配置文件提供，避免提交密钥与敏感信息。
