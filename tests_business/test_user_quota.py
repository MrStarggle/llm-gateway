"""用户级 Token 配额与访问封禁集成测试"""
import asyncio
import json
from datetime import date, timedelta
from unittest.mock import patch

import httpx
from sqlalchemy import select

from app.models.model_manage_info import ModelManageInfo
from app.models.user_daily_quota import UserDailyQuota
from app.models.user_token_info import UserTokenInfo
from app.schemas.health_manage import RoutingConfigUpdate
from app.schemas.project_manage import ProjectCreate, TokenCreate
from app.services import (
    call_manage_service,
    health_manage_service,
    project_manage_service,
    user_quota_service,
)
from tests_business.base import BusinessGatewayTestCase, seed_user

import app.api.v1.controller.call_manage_controller as ctrl

CHAT_PATH = "/v1/chat/completions"
ADMIN_PATH = "/api/v1/user-manage"
BODY = {"model": "", "messages": [{"role": "user", "content": "hi"}]}


async def _prepare_gateway(session_factory):
    """插入一个可用模型，供转发链路选择."""
    async with session_factory() as db:
        db.add(ModelManageInfo(
            ai_model_id="q1",
            ai_model_name="quota-model",
            com_name="mock",
            com_url="https://mock.example/v1",
            api_key="upstream-key",
            is_using="1",
            async_type="async1",
            input_price_per_1m=1,
            output_price_per_1m=2,
            price_currency="USD",
        ))
        await db.commit()
        await health_manage_service.update_routing_config(
            db, "async1",
            RoutingConfigUpdate(
                strategy="round_robin", retry_max=0,
                failure_threshold=5, cooldown_seconds=60,
            ),
        )


async def _prepare_project_token(session_factory):
    async with session_factory() as db:
        project = await project_manage_service.create_project(
            db, ProjectCreate(project_name="quota-project"),
        )
        token, raw = await project_manage_service.create_token(
            db, project.project_id, TokenCreate(name="prod"),
        )
        return token, raw


async def _set_policy(session_factory, user_id, *, daily=None, monthly=None,
                      status="active"):
    async with session_factory() as db:
        await user_quota_service.upsert_quota_policy(
            db, user_id,
            daily_token_limit=daily,
            monthly_token_limit=monthly,
            access_status=status,
            remark=None,
        )


async def _seed_daily(session_factory, user_id, *, calls=0, tokens=0, day=None):
    async with session_factory() as db:
        db.add(UserDailyQuota(
            user_id=user_id,
            quota_date=day or date.today(),
            call_count=calls,
            total_tokens=tokens,
        ))
        await db.commit()


def _fake_client(real_client, handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    return factory


def _usage_handler(calls, total_tokens=15):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": max(0, total_tokens - 5),
                "completion_tokens": 5,
                "total_tokens": total_tokens,
            },
        })

    return handler


def _stream_handler(calls, total_tokens=10):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        sse = (
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            f'data: {{"usage":{{"prompt_tokens":7,"completion_tokens":3,'
            f'"total_tokens":{total_tokens}}}}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"},
        )

    return handler


class UserQuotaTest(BusinessGatewayTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await _prepare_gateway(self.Session)
        await seed_user(self.Session, "u1")

    async def _daily_row(self, user_id="u1") -> UserDailyQuota | None:
        async with self.Session() as db:
            return (await db.execute(
                select(UserDailyQuota).where(
                    UserDailyQuota.user_id == user_id,
                    UserDailyQuota.quota_date == date.today(),
                )
            )).scalar_one_or_none()

    async def test_blocked_user_plain_call_403(self):
        await _set_policy(self.Session, "u1", status="blocked")
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "user_blocked")
        self.assertEqual(calls, [])

    async def test_blocked_sk_token_with_explicit_user_403(self):
        _, raw = await _prepare_project_token(self.Session)
        await _set_policy(self.Session, "u1", status="blocked")
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH,
                headers={"Authorization": f"Bearer {raw}", "X-User-Id": "u1"},
                json=BODY,
            )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "user_blocked")
        self.assertEqual(calls, [])

    async def test_blocked_sk_token_gw_fallback_403(self):
        token, raw = await _prepare_project_token(self.Session)
        await _set_policy(self.Session, f"gw:{token.token_id}", status="blocked")
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH, headers={"Authorization": f"Bearer {raw}"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "user_blocked")
        self.assertEqual(calls, [])

    async def test_blocked_gw_token_with_explicit_user_403(self):
        """显式 X-User-Id 未封禁，但 gw:<token_id> 被封禁也要拦截."""
        token, raw = await _prepare_project_token(self.Session)
        await _set_policy(self.Session, f"gw:{token.token_id}", status="blocked")
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH,
                headers={"Authorization": f"Bearer {raw}", "X-User-Id": "u1"},
                json=BODY,
            )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "user_blocked")
        self.assertEqual(calls, [])

    async def test_daily_token_limit_reached_429(self):
        await _set_policy(self.Session, "u1", daily=100)
        await _seed_daily(self.Session, "u1", tokens=100)
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["code"], "daily_token_quota_exceeded")
        self.assertEqual(resp.json()["error"]["type"], "rate_limit_error")
        self.assertEqual(calls, [])

    async def test_daily_zero_limit_blocks(self):
        await _set_policy(self.Session, "u1", daily=0)
        resp = await self.client.post(
            CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
        )
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["code"], "daily_token_quota_exceeded")

    async def test_under_daily_limit_allows_and_increments(self):
        await _set_policy(self.Session, "u1", daily=100)
        await _seed_daily(self.Session, "u1", tokens=99)
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls, 15))):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 200)
        row = await self._daily_row()
        self.assertIsNotNone(row)
        self.assertEqual(row.call_count, 1)
        self.assertEqual(row.total_tokens, 114)

    async def test_monthly_token_limit_across_days_429(self):
        month_start = date.today().replace(day=1)
        await _set_policy(self.Session, "u1", monthly=1000)
        await _seed_daily(self.Session, "u1", tokens=1000, day=month_start)
        resp = await self.client.post(
            CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
        )
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["code"], "monthly_token_quota_exceeded")

    async def test_null_limits_are_unlimited(self):
        await _set_policy(self.Session, "u1", daily=None, monthly=None)
        await _seed_daily(self.Session, "u1", tokens=10 ** 9)
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 200)

    async def test_previous_month_usage_excluded(self):
        month_start = date.today().replace(day=1)
        prev_day = month_start - timedelta(days=1)
        await _set_policy(self.Session, "u1", monthly=1000)
        await _seed_daily(self.Session, "u1", tokens=10 ** 6, day=prev_day)
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _usage_handler(calls))):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 200)

    async def test_stream_usage_increments_token_counter(self):
        calls = []
        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, _stream_handler(calls))), \
             patch("app.config.database.AsyncSessionLocal", self.Session):
            resp = await self.client.post(
                CHAT_PATH,
                headers={"X-User-Id": "u1"},
                json={"model": "", "stream": True,
                      "messages": [{"role": "user", "content": "hi"}]},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("hi", resp.text)
            # 保持在 AsyncSessionLocal patch 生效期间等待后台记账任务完成
            pending = list(call_manage_service._background_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        row = await self._daily_row()
        self.assertIsNotNone(row)
        self.assertEqual(row.call_count, 1)
        self.assertEqual(row.total_tokens, 10)

    async def test_missing_total_tokens_falls_back_to_sum(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            })

        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, handler)):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 200)
        row = await self._daily_row()
        self.assertEqual(row.total_tokens, 12)
        async with self.Session() as db:
            detail = (await db.execute(
                select(UserTokenInfo).where(UserTokenInfo.user_id == "u1")
            )).scalars().all()
            self.assertEqual(len(detail), 1)
            self.assertEqual(detail[0].total_tokens, 12)

    async def test_empty_usage_counts_call_only(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ok"}}],
            })

        with patch.object(ctrl.httpx, "AsyncClient",
                          _fake_client(httpx.AsyncClient, handler)):
            resp = await self.client.post(
                CHAT_PATH, headers={"X-User-Id": "u1"}, json=BODY,
            )
        self.assertEqual(resp.status_code, 200)
        row = await self._daily_row()
        self.assertEqual(row.call_count, 1)
        self.assertEqual(row.total_tokens, 0)

    async def test_admin_quota_upsert_get_and_clear(self):
        resp = await self.client.put(
            f"{ADMIN_PATH}/u1/quota",
            json={
                "daily_token_limit": 1000,
                "monthly_token_limit": 20000,
                "access_status": "blocked",
                "remark": "测试",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 200)
        data = body["data"]
        self.assertEqual(data["userId"], "u1")
        self.assertEqual(data["dailyTokenLimit"], 1000)
        self.assertEqual(data["monthlyTokenLimit"], 20000)
        self.assertEqual(data["accessStatus"], "blocked")
        self.assertEqual(data["remark"], "测试")
        self.assertTrue(data["userExists"])

        got = await self.client.get(f"{ADMIN_PATH}/u1/quota")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["data"]["accessStatus"], "blocked")

        cleared = await self.client.put(
            f"{ADMIN_PATH}/u1/quota",
            json={"daily_token_limit": None, "monthly_token_limit": None,
                  "access_status": "active", "remark": None},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["data"]["dailyTokenLimit"])
        self.assertEqual(cleared.json()["data"]["accessStatus"], "active")

        bad = await self.client.put(
            f"{ADMIN_PATH}/u1/quota",
            json={"daily_token_limit": 1, "access_status": "weird"},
        )
        self.assertEqual(bad.status_code, 422)

        missing_status = await self.client.put(
            f"{ADMIN_PATH}/u1/quota",
            json={"daily_token_limit": 1},
        )
        self.assertEqual(missing_status.status_code, 422)

        ghost = await self.client.get(f"{ADMIN_PATH}/ghost/quota")
        self.assertEqual(ghost.status_code, 200)
        self.assertFalse(ghost.json()["data"]["userExists"])

    async def test_admin_list_includes_quota_fields(self):
        await seed_user(self.Session, "u2")
        await _set_policy(self.Session, "u1", daily=1000, monthly=5000)
        await _seed_daily(self.Session, "u1", calls=2, tokens=123)

        resp = await self.client.get(
            f"{ADMIN_PATH}/list", params={"page": 1, "page_size": 20},
        )
        self.assertEqual(resp.status_code, 200)
        rows = {row["userId"]: row for row in resp.json()["data"]["list"]}
        self.assertEqual(rows["u1"]["dailyTokenLimit"], 1000)
        self.assertEqual(rows["u1"]["monthlyTokenLimit"], 5000)
        self.assertEqual(rows["u1"]["todayTokens"], 123)
        self.assertEqual(rows["u1"]["monthTokens"], 123)
        self.assertEqual(rows["u1"]["accessStatus"], "active")
        self.assertEqual(rows["u2"]["accessStatus"], "active")
        self.assertIsNone(rows["u2"]["dailyTokenLimit"])
        self.assertEqual(rows["u2"]["todayTokens"], 0)

    async def test_orders_route_still_resolves(self):
        resp = await self.client.get(f"{ADMIN_PATH}/orders")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 200)
        self.assertEqual(resp.json()["data"]["total"], 0)

    async def test_reset_call_count_preserves_tokens(self):
        await _seed_daily(self.Session, "u1", calls=5, tokens=100)
        resp = await self.client.post(
            f"{ADMIN_PATH}/reset-call-count", json={"user_id": "u1"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 200)
        self.assertEqual(body["data"]["updatedRows"], 1)
        self.assertEqual(body["data"]["todayUsed"], 0)
        self.assertEqual(body["data"]["todayTokens"], 100)

        row = await self._daily_row()
        self.assertEqual(row.call_count, 0)
        self.assertEqual(row.total_tokens, 100)
