# 贡献指南

[English](CONTRIBUTING.md) | **简体中文**

## 开发环境

需要 Python 3.10+。

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

默认使用 SQLite，无需额外数据库；需要 MySQL 时参考 README 的「切换到 MySQL」。

## 测试

测试只依赖 Python 标准库，使用独立的临时 SQLite 文件，不会修改 `data/gateway.db`：

```bash
python -m unittest discover -s tests -v
```

提交 PR 前请确保全部测试通过。新增功能请附带覆盖核心行为的测试。

## 代码风格

- 遵循 PEP 8，函数保持职责单一，避免深层嵌套
- 异步路由中不要调用阻塞 IO 或同步数据库会话
- 管理接口统一通过 `Depends(verify_admin_token)` 鉴权
- 输入在系统边界校验，错误显式处理，不要静默吞掉
- 日志中不要输出请求体、API Key、项目 Token 或用户提示词（`GATEWAY_DEBUG=1` 除外）

## 提交信息

使用 Conventional Commits：

```text
feat: 新增功能
fix: 修复问题
docs: 文档
test: 测试
refactor: 重构
perf: 性能
chore: 构建或杂项
```

## 提交 Pull Request

1. Fork 仓库，从 `main` 创建功能分支
2. 保持改动聚焦，一个 PR 只做一件事
3. 说明改动动机、行为变化和测试方式
4. 确认没有提交 `.env`、数据库文件、日志或任何密钥
5. 涉及安全相关改动时，请在描述中单独说明
