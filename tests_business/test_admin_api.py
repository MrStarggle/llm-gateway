"""business-sync 项目管理与渠道健康 API 冒烟测试"""
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
