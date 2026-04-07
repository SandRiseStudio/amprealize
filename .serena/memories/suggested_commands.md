# Suggested Commands

## Python / Core
- **Run Tests**: `pytest` or `pytest -m unit`
- **Run Specific Test**: `pytest tests/test_filename.py`
- **Install Dependencies**: `pip install -r requirements.txt` (or `uv sync` if using uv)
- **CLI Entry**: `amprealize --help`
- **Secret Scan**: `scripts/scan_secrets.sh` or `pre-commit run gitleaks --all-files`
- **Pre-commit**: `pre-commit run --all-files`

## VS Code Extension
- **Install Dependencies**: `cd extension && npm install`
- **Build**: `cd extension && npm run compile`
- **Watch**: `cd extension && npm run watch`
- **Package**: `cd extension && npm run package`

## Docker
- **Start Services**: `docker-compose up -d`
