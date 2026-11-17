"""项目、Token 与配额服务测试"""
from decimal import Decimal

# 必须先导入 tests.base：它在导入 app 之前设置独立测试数据库
from tests.base import GatewayTestCase
from app.config.database import AsyncSessionLocal
from app.schemas.project_manage import ProjectCreate, TokenCreate
from app.services import project_manage_service as svc


class ProjectServiceTest(GatewayTestCase):
    async def test_token_lifecycle_and_allowed_models(self):
        async with AsyncSessionLocal() as db:
            project = await svc.create_project(
                db, ProjectCreate(project_name="project-1", daily_call_limit=2),
            )
            token, raw = await svc.create_token(
                db, project.project_id,
                TokenCreate(name="web-prod", allowed_models=["gpt-*"]),
            )
            self.assertTrue(raw.startswith(svc.TOKEN_PREFIX))
            self.assertNotEqual(token.token_hash, raw)
            self.assertEqual(len(token.token_hash), 64)

            identity = await svc.resolve_gateway_token(db, raw)
            self.assertEqual(identity.project.project_id, project.project_id)
            self.assertTrue(svc.model_allowed(identity, "gpt-4o"))
            self.assertFalse(svc.model_allowed(identity, "claude-3"))

            rotated_token, new_raw = await svc.rotate_token(db, token.token_id, None)
            self.assertNotEqual(new_raw, raw)
            with self.assertRaises(svc.GatewayAuthError):
                await svc.resolve_gateway_token(db, raw)
            await svc.resolve_gateway_token(db, new_raw)

            await svc.revoke_token(db, rotated_token.token_id)
            with self.assertRaises(svc.GatewayAuthError) as ctx:
                await svc.resolve_gateway_token(db, new_raw)
            self.assertEqual(ctx.exception.code, "api_key_revoked")

    async def test_project_usage_and_quota(self):
        async with AsyncSessionLocal() as db:
            project = await svc.create_project(
                db,
                ProjectCreate(
                    project_name="project-quota",
                    daily_call_limit=1,
                    daily_token_limit=100,
                    daily_cost_limit=0.5,
                    cost_currency="USD",
                ),
            )
            await svc.increment_project_usage(
                db, project.project_id, project_currency="USD",
                tokens=10, cost=Decimal("0.1"), cost_currency="USD",
            )
            snapshot = await svc.get_usage_snapshot(db, project.project_id)
            self.assertEqual(snapshot.today_calls, 1)
            self.assertEqual(snapshot.today_tokens, 10)
            self.assertEqual(snapshot.today_cost, Decimal("0.1"))

            # 其他币种不计入项目成本
            await svc.increment_project_usage(
                db, project.project_id, project_currency="USD",
                tokens=20, cost=Decimal("99"), cost_currency="CNY",
            )
            snapshot = await svc.get_usage_snapshot(db, project.project_id)
            self.assertEqual(snapshot.today_tokens, 30)
            self.assertEqual(snapshot.today_cost, Decimal("0.1"))

            with self.assertRaises(svc.ProjectQuotaError) as ctx:
                svc.check_project_quota(project, snapshot)
            self.assertEqual(ctx.exception.code, "daily_call_quota_exceeded")

            blocked = await svc.create_project(
                db, ProjectCreate(project_name="blocked", daily_call_limit=0),
            )
            with self.assertRaises(svc.ProjectQuotaError) as ctx:
                svc.check_project_quota(
                    blocked, await svc.get_usage_snapshot(db, blocked.project_id),
                )
            self.assertEqual(ctx.exception.code, "daily_call_quota_exceeded")

    async def test_project_can_be_disabled(self):
        async with AsyncSessionLocal() as db:
            project = await svc.create_project(db, ProjectCreate(project_name="disabled"))
            _, raw = await svc.create_token(
                db, project.project_id, TokenCreate(name="key"),
            )
            project.status = "disabled"
            await db.commit()
            with self.assertRaises(svc.GatewayAuthError) as ctx:
                await svc.resolve_gateway_token(db, raw)
            self.assertEqual(ctx.exception.code, "project_disabled")
            self.assertEqual(ctx.exception.status_code, 403)
