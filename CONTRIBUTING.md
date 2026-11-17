# Contributing

**English** | [简体中文](CONTRIBUTING.zh-CN.md)

## Development environment

Requires Python 3.10+.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 9010 --reload
```

SQLite is the default and needs no extra database. See "Switching to MySQL" in the README if you
need MySQL.

## Tests

The tests depend only on the Python standard library and use a separate temporary SQLite file, so
they never modify `data/gateway.db`:

```bash
python -m unittest discover -s tests -v
```

Make sure the full suite passes before opening a pull request. New features should include tests
covering the core behavior.

## Code style

- Follow PEP 8; keep functions focused and avoid deep nesting
- Do not perform blocking I/O or use synchronous database sessions in async endpoints
- Guard admin endpoints with `Depends(verify_admin_token)`
- Validate input at system boundaries and handle errors explicitly; never swallow them silently
- Do not log request bodies, API keys, project tokens, or user prompts (except with `GATEWAY_DEBUG=1`)

## Commit messages

Use Conventional Commits:

```text
feat: add a feature
fix: fix a bug
docs: documentation
test: tests
refactor: refactor
perf: performance
chore: build or maintenance
```

## Pull requests

1. Fork the repository and branch from `main`
2. Keep the change focused: one pull request, one concern
3. Explain the motivation, behavior changes, and how it was tested
4. Make sure no `.env`, database files, logs, or secrets are committed
5. Call out security-relevant changes explicitly in the description
