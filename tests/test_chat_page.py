"""内置聊天页与 /v1/models 列表测试."""
from tests.base import GatewayTestCase
import httpx

from app.config.database import AsyncSessionLocal
from app.models.model_manage_info import ModelManageInfo
from app.schemas.project_manage import ProjectCreate, TokenCreate
from app.services import project_manage_service
from main import app


class ChatPageTest(GatewayTestCase):
    async def _seed_models(self) -> None:
        async with AsyncSessionLocal() as db:
            db.add_all([
                ModelManageInfo(
                    ai_model_id="chat-m1",
                    ai_model_name="model-a",
                    com_name="provider-a",
                    com_url="https://a.example/v1",
                    api_key="upstream-a",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async1",
                    input_price_per_1m=1.5,
                    output_price_per_1m=3,
                    price_currency="USD",
                ),
                ModelManageInfo(
                    ai_model_id="chat-m2",
                    ai_model_name="model-a",
                    com_name="provider-a",
                    com_url="https://a.example/v1",
                    api_key="upstream-a",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async2",
                ),
                ModelManageInfo(
                    ai_model_id="chat-m3",
                    ai_model_name="model-b",
                    com_name="provider-b",
                    com_url="https://b.example/v1",
                    api_key="upstream-b",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async1",
                ),
                ModelManageInfo(
                    ai_model_id="chat-m4",
                    ai_model_name="model-off",
                    com_name="provider-b",
                    com_url="https://b.example/v1",
                    api_key="upstream-b",
                    ai_model_type="0",
                    is_using="0",
                    async_type="async1",
                ),
                ModelManageInfo(
                    ai_model_id="chat-m6",
                    ai_model_name="model-a",
                    com_name="provider-c",
                    com_url="https://c.example/v1",
                    api_key="upstream-c",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async3",
                ),
                ModelManageInfo(
                    ai_model_id="chat-m5",
                    ai_model_name="speech-model",
                    com_name="provider-b",
                    com_url="https://b.example/v1",
                    api_key="upstream-b",
                    ai_model_type="1",
                    is_using="1",
                    async_type="async1",
                ),
            ])
            await db.commit()

    async def test_chat_page_is_served(self):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        try:
            resp = await client.get("/chat")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("cache-control"), "no-store")
            self.assertIn("/static/chat/chat.js", resp.text)
            self.assertIn('id="messages"', resp.text)
            self.assertIn("StarggleAPI Chat", resp.text)
        finally:
            await client.aclose()

    async def test_models_list_groups_active_text_models(self):
        await self._seed_models()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        try:
            resp = await client.get("/v1/models")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload["object"], "list")
            by_id = {item["id"]: item for item in payload["data"]}
            self.assertEqual(set(by_id), {"model-a", "model-b"})
            self.assertEqual(by_id["model-a"]["x_clusters"], ["async1", "async2", "async3"])
            self.assertEqual(by_id["model-a"]["x_async_type"], "async1")
            self.assertEqual(by_id["model-a"]["x_providers"], ["provider-a", "provider-c"])
            self.assertEqual(by_id["model-a"]["owned_by"], "provider-a")
            self.assertEqual(by_id["model-a"]["x_pricing"]["input_per_1m"], 1.5)
            self.assertNotIn("api_key", by_id["model-a"])
        finally:
            await client.aclose()

    async def test_models_list_filters_by_project_token(self):
        await self._seed_models()
        async with AsyncSessionLocal() as db:
            project = await project_manage_service.create_project(
                db, ProjectCreate(project_name="chat-models"),
            )
            _, raw = await project_manage_service.create_token(
                db, project.project_id,
                TokenCreate(name="chat-key", allowed_models=["model-a"]),
            )

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        try:
            resp = await client.get(
                "/v1/models", headers={"Authorization": f"Bearer {raw}"},
            )
            self.assertEqual(resp.status_code, 200)
            ids = {item["id"] for item in resp.json()["data"]}
            self.assertEqual(ids, {"model-a"})

            bad = await client.get(
                "/v1/models", headers={"Authorization": "Bearer sk-gw-invalid"},
            )
            self.assertEqual(bad.status_code, 401)
            self.assertEqual(bad.json()["error"]["code"], "invalid_api_key")
        finally:
            await client.aclose()
