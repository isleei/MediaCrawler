# Repository Guidelines

## Project Structure
Core modules: `main.py` (CLI entry), `api/` (FastAPI WebUI), `media_platform/` (platform scrapers), `base/` (abstract base classes), `config/` (configuration), `store/`/`database/` (data persistence), `proxy/`/`cache/`/`libs/` (utilities). Tests in `tests/` (pytest) and `test/` (unittest/integration).

## Build & Run Commands
```sh
# Install dependencies (recommended)
uv sync
uv run playwright install

# Run crawler
uv run main.py --platform xhs --lt qrcode --type search

# Alternative: venv + pip
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install
python main.py --platform xhs --lt qrcode --type search

# WebUI
uv run uvicorn api.main:app --port 8080 --reload

# Pre-commit hooks
pre-commit run --all-files
```

## Testing
```sh
# Run all tests
pytest

# Run single test file (pytest)
pytest tests/test_excel_store.py

# Run single test with verbose output
pytest tests/test_store_factory.py -v

# Run specific test function
pytest tests/test_excel_store.py::test_csv_store -v

# Run unittest/integration tests
python test/test_mongodb_integration.py
python test/test_redis_cache.py

# Run with coverage
pytest --cov=store tests/

# Async tests use pytest-asyncio
pytest tests/test_excel_store.py -v
```

Note: Tests requiring MongoDB/Redis need local services running.

## Code Style & Conventions
- **Python Version**: >=3.11
- **PEP 8**: 4-space indentation, snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants
- **Encoding**: UTF-8 with `# -*- coding: utf-8 -*-` header
- **Imports**: Group in order: stdlib, third-party, local (separated by blank lines)
- **Async/await**: Use for I/O operations with `asyncio`
- **Type hints**: Required for function signatures (return types, args)
  ```python
  async def process_data(self, data: Dict) -> Optional[List[str]]:
  ```

## File Headers
All Python files must include copyright header:
```python
# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/...
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

# 声明：本代码仅供学习和研究目的使用...
```

## Error Handling
- Use custom exceptions in each module (e.g., `DataFetchError`, `IPBlockError`)
- Wrap async operations in try-except blocks
- Use `tenacity` for retries:
  ```python
  @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
  async def request(self, method, url, **kwargs):
  ```

## Naming & Patterns
- **Factories**: `*Factory` classes with `create_*()` static methods
- **Mixins**: `*Mixin` for shared functionality
- **Config**: Uppercase constants in `config/*.py`
- **Models**: `*Item` or `*Model` classes for data structures
- **Logging**: Use `from tools import utils; utils.logger.info(...)`

## Type Checking
```sh
# Configure in mypy.ini
mypy . --ignore-missing-imports

# Check specific module
mypy media_platform/xhs/
```

## Configuration
- All crawler settings in `config/base_config.py` (Chinese comments)
- Platform-specific configs in `config/*_config.py`
- Environment variables via `.env` (not committed)
- No hardcoded credentials - use config or env vars

## Commit & PR Guidelines
- Conventional Commits: `feat(scope):`, `fix:`, `refactor:`, `docs:`, `test:`
- Examples: `feat(xhs): add note detail scraping`, `fix: resolve IP proxy timeout`
- PR description: explain motivation, scope, and verification steps
- For WebUI/docs changes: attach screenshots or command output

## Dependencies
- Async HTTP: `httpx`, `aiofiles`
- Browser automation: `playwright`
- Data: `pandas`, `openpyxl`
- Retry logic: `tenacity`
- Config: `python-dotenv`

## Security
- Never commit `.env` files or credentials
- Use environment variables for secrets (DB passwords, API keys)
- Log sensitive data with caution
- Check `tools/file_header_manager.py` for copyright enforcement
