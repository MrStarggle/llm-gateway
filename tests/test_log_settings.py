"""LLM 报文日志开关测试"""
import httpx

from tests.base import GatewayTestCase
from app.config.database import AsyncSessionLocal
from app.services import log_settings_service as svc
from main import app


class LogSettingsTest(GatewayTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with AsyncSessionLocal() as db:
            await svc.load(db)

    async def test_default_enabled_and_toggle(self):
        self.assertTrue(svc.is_payload_logging_enabled())

        async with AsyncSessionLocal() as db:
            self.assertFalse(await svc.set_enabled(db, False))
        self.assertFalse(svc.is_payload_logging_enabled())

        async with AsyncSessionLocal() as db:
            self.assertFalse(await svc.get_enabled(db))
            self.assertTrue(await svc.set_enabled(db, True))
        self.assertTrue(svc.is_payload_logging_enabled())

    async def test_api_default_and_toggle(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "testpass"},
            )
            self.assertEqual(login.status_code, 200)
            token = login.json()["data"]["token"]
            headers = {"Authorization": f"Bearer {token}"}

            resp = await client.get("/api/v1/health-manage/log-settings", headers=headers)
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["data"]["enabled"])

            resp = await client.put(
                "/api/v1/health-manage/log-settings",
                headers=headers,
                json={"enabled": False},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["data"]["enabled"])
            self.assertFalse(svc.is_payload_logging_enabled())
