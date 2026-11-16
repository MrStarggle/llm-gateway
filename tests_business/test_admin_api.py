"""business-sync 项目管理与渠道健康 API 冒烟测试"""
from app.schemas.model_manage import ModelManageCreate
from app.services import model_manage_service
from tests_business.base import BusinessGatewayTestCase


class BusinessAdminApiTest(BusinessGatewayTestCase):
    async def test_project_token_and_health_api(self):
        resp = await self.client.post(
            "/api/v1/project-manage/projects",
            json={"project_name": "API 项目", "daily_call_limit": 10},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 201)
        project_id = resp.json()["data"]["projectId"]

        resp = await self.client.post(
            f"/api/v1/project-manage/projects/{project_id}/tokens",
            json={"name": "prod", "allowed_models": ["gpt-*"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["token"].startswith("sk-gw-"))

        resp = await self.client.get(
            "/api/v1/project-manage/projects", params={"keyword": "API"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["total"], 1)

        resp = await self.client.get("/api/v1/health-manage/overview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 200)
        self.assertEqual(len(resp.json()["data"]["clusters"]), 9)

        resp = await self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("sec-projects", resp.text)
        self.assertIn("sec-health", resp.text)
        self.assertIn('id="sec-users"', resp.text)
        self.assertIn('data-section="users"', resp.text)
        self.assertIn('id="userBody"', resp.text)
        self.assertIn('id="orderBody"', resp.text)

    async def test_user_manage_page_redirects_to_console_section(self):
        resp = await self.client.get("/user-manage", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers["location"], "/model-manage#users")

    async def test_model_copy_batch_order(self):
        """复制模型沿用源批次，列表中副本紧跟源模型；新批次排在最前。"""
        async with self.Session() as db:
            source = await model_manage_service.create_model(db, ModelManageCreate(
                ai_model_name="copy-src", com_name="mock", com_url="https://mock/v1",
                api_key="k", is_using="1", batch_no=1000,
            ))
            copied = await model_manage_service.create_model(db, ModelManageCreate(
                ai_model_name="copy-src", com_name="mock", com_url="https://mock/v1",
                api_key="k", is_using="1", batch_no=1000,
            ))
            newer = await model_manage_service.create_model(db, ModelManageCreate(
                ai_model_name="newer", com_name="mock", com_url="https://mock/v1",
                api_key="k", is_using="1", batch_no=2000,
            ))
            rows = await model_manage_service.get_model_list(db)

        ids = [m.ai_model_id for m in rows]
        self.assertEqual(ids[0], newer.ai_model_id)
        self.assertEqual(ids[1:3], [source.ai_model_id, copied.ai_model_id])
