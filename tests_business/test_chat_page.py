"""业务分支：内置聊天页与 /v1/models 测试."""
import os

os.environ["GATEWAY_TOKEN_REQUIRED"] = "0"

from tests_business.base import BusinessGatewayTestCase  # noqa: E402

from app.models.model_manage_info import ModelManageInfo  # noqa: E402
from app.schemas.project_manage import ProjectCreate, TokenCreate  # noqa: E402
from app.services import project_manage_service  # noqa: E402


class ChatPageBusinessTest(BusinessGatewayTestCase):
    async def _seed_models(self) -> None:
        async with self.Session() as db:
            db.add_all([
                ModelManageInfo(
                    ai_model_id="biz-m1",
                    ai_model_name="model-a",
                    com_name="provider-a",
                    com_url="https://a.example/v1",
                    api_key="upstream-a",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async1",
                ),
                ModelManageInfo(
                    ai_model_id="biz-m2",
                    ai_model_name="model-b",
                    com_name="provider-b",
                    com_url="https://b.example/v1",
                    api_key="upstream-b",
                    ai_model_type="0",
                    is_using="1",
                    async_type="async2",
                ),
                ModelManageInfo(
                    ai_model_id="biz-m3",
                    ai_model_name="model-off",
                    com_name="provider-b",
                    com_url="https://b.example/v1",
                    api_key="upstream-b",
                    ai_model_type="0",
                    is_using="0",
                    async_type="async1",
                ),
            ])
            await db.commit()

    async def test_chat_page_is_served(self):
        resp = await self.client.get("/chat")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        self.assertIn("/static/chat/chat.js", resp.text)
        self.assertIn('id="messages"', resp.text)

    async def test_models_list_and_token_filter(self):
        await self._seed_models()
        async with self.Session() as db:
            project = await project_manage_service.create_project(
                db, ProjectCreate(project_name="biz-chat-models"),
            )
            _, raw = await project_manage_service.create_token(
                db, project.project_id,
                TokenCreate(name="biz-chat-key", allowed_models=["model-a"]),
            )

        resp = await self.client.get("/v1/models")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({item["id"] for item in resp.json()["data"]}, {"model-a", "model-b"})

        allowed = await self.client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw}"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual({item["id"] for item in allowed.json()["data"]}, {"model-a"})

        bad = await self.client.get(
            "/v1/models", headers={"Authorization": "Bearer sk-gw-invalid"},
        )
        self.assertEqual(bad.status_code, 401)
