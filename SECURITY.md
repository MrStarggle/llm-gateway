# Security Policy

**English** | [简体中文](SECURITY.zh-CN.md)

## Reporting a vulnerability

Please do **not** report security vulnerabilities through public issues. Use GitHub's private
vulnerability reporting:

<https://github.com/MrStarggle/llm-gateway/security/advisories/new>

Please include as much as possible:

- Affected version or commit
- Reproduction steps and a minimal request
- Impact (e.g. reading other users' data, bypassing quotas, obtaining upstream keys)
- Suggested fix (optional)

We will respond as soon as we can after confirming the issue, and will credit you in the release
notes if you wish.

## Supported versions

| Version | Status |
|---|---|
| Latest commit on `main` | Supported |
| Older commits or other branches | Not guaranteed; upgrade to the latest first |

## Deployer responsibilities

This project is a self-hosted gateway. Operators are responsible for securing their deployment:

- Change the default `ADMIN_USERNAME` / `ADMIN_PASSWORD` and `JWT_SECRET_KEY`
- Serve over HTTPS behind a reverse proxy, and restrict admin console access at the proxy
- Never commit `.env`, `data/`, database files, logs, or any upstream API key
- `GATEWAY_DEBUG=1` logs request bodies and model responses; keep it `0` in production
- Project tokens are stored as SHA-256 hashes; the full secret is shown only once at creation/rotation — store it securely
- Rate-limit the login endpoint at the reverse proxy if it is exposed to the internet
