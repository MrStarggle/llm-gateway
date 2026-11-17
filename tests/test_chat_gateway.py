"""聊天入口集成测试：Token 鉴权、配额、重试、流式记账、请求 ID"""
import asyncio
from unittest.mock import patch

# 必须先导入 tests.base：它在导入 app 之前设置独立测试数据库
from tests.base import GatewayTestCase
import httpx
from sqlalchemy import select

from app.config.database import AsyncSessionLocal
from app.models.channel_health_info import ChannelHealthInfo
from app.models.model_manage_info import ModelManageInfo
from app.models.project_usage_daily import ProjectUsageDaily
from app.models.user_token_info import UserTokenInfo
from app.schemas.health_manage import RoutingConfigUpdate
from app.schemas.project_manage import ProjectCreate, TokenCreate
from app.services import health_manage_service, project_manage_service
from main import app

import app.api.v1.controller.call_manage_controller as ctrl


async def _prepare_cluster_project():
    async with AsyncSessionLocal() as db:
        for model_id, name in (("m1", "mock-model-1"), ("m2", "mock-model-2")):
            db.add(ModelManageInfo(
                ai_model_id=model_id,
                ai_model_name=name,
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
                strategy="round_robin", retry_max=1,
                failure_threshold=5, cooldown_seconds=60,
            ),
        )
        project = await project_manage_service.create_project(
            db, ProjectCreate(project_name="chat-test"),
        )
        token, raw = await project_manage_service.create_token(
            db, project.project_id, TokenCreate(name="test-key"),
        )
        return project.project_id, token.token_id, raw


def _fake_client_factory(real_client, handler):
    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    return fake_client


class ChatGatewayTest(GatewayTestCase):
    async def test_non_stream_retry_records_usage(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(500, text='{"error":"boom"}')
            return httpx.Response(200, json={
                "id": "x",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })

        project_id, _, raw = await _prepare_cluster_project()
        real_client = httpx.AsyncClient
        client = real_client(transport=httpx.ASGITransport(app=app), base_url="http://test")
        try:
            with patch.object(ctrl.httpx, "AsyncClient", _fake_client_factory(real_client, handler)):
                resp = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "", "messages": [{"role": "user", "content": "hi"}]},
                )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["choices"][0]["message"]["content"], "ok")
            self.assertEqual(resp.headers["x-gateway-retry-count"], "1")
            self.assertTrue(resp.headers["x-request-id"])
            self.assertEqual(len(calls), 2)
        finally:
            await client.aclose()

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(UserTokenInfo).where(UserTokenInfo.project_id == project_id)
            )).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].total_tokens, 15)
            self.assertEqual(rows[0].retry_count, 1)
            self.assertTrue(rows[0].request_id)
            daily = (await db.execute(
                select(ProjectUsageDaily).where(ProjectUsageDaily.project_id == project_id)
            )).scalars().all()
            self.assertEqual(len(daily), 1)
            self.assertEqual(daily[0].call_count, 1)
            self.assertEqual(daily[0].total_tokens, 15)
            health = (await db.execute(select(ChannelHealthInfo))).scalars().all()
            self.assertEqual(sum(h.failure_count for h in health), 1)
            self.assertEqual(sum(h.success_count for h in health), 1)

    async def test_stream_retry_and_background_usage(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(500, text='{"error":"boom"}')
            sse = (
                'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                'data: {"choices":[{"delta":{}}],"usage":'
                '{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(
                200, content=sse.encode(), headers={"content-type": "text/event-stream"},
            )

        project_id, _, raw = await _prepare_cluster_project()
        real_client = httpx.AsyncClient
        client = real_client(transport=httpx.ASGITransport(app=app), base_url="http://test")
        try:
            with patch.object(ctrl.httpx, "AsyncClient", _fake_client_factory(real_client, handler)):
                resp = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={
                        "model": "", "stream": True,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("hi", resp.text)
            self.assertEqual(resp.headers["x-gateway-retry-count"], "1")
        finally:
            await client.aclose()

        # 流式用量由独立后台任务写入
        await asyncio.sleep(0.2)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(UserTokenInfo).where(UserTokenInfo.project_id == project_id)
            )).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].total_tokens, 10)
            self.assertEqual(rows[0].retry_count, 1)

    async def test_quota_and_invalid_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })

        project_id, _, raw = await _prepare_cluster_project()
        async with AsyncSessionLocal() as db:
            project = await project_manage_service.get_project(db, project_id)
            project.daily_call_limit = 1
            await db.commit()

        real_client = httpx.AsyncClient
        client = real_client(transport=httpx.ASGITransport(app=app), base_url="http://test")
        try:
            with patch.object(ctrl.httpx, "AsyncClient", _fake_client_factory(real_client, handler)):
                first = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "", "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(first.status_code, 200)

                second = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "", "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(second.status_code, 429)
                self.assertEqual(second.json()["error"]["code"], "daily_call_quota_exceeded")

                invalid = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer sk-gw-invalid"},
                    json={"model": "", "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(invalid.status_code, 401)
                self.assertEqual(invalid.json()["error"]["code"], "invalid_api_key")
        finally:
            await client.aclose()
