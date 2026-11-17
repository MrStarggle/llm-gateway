"""渠道健康状态机与路由策略测试"""
# 必须先导入 tests.base：它在导入 app 之前设置独立测试数据库
from tests.base import GatewayTestCase
from app.config.database import AsyncSessionLocal
from app.models.model_manage_info import ModelManageInfo
from app.schemas.health_manage import RoutingConfigUpdate
from app.services import health_manage_service as svc


def _model(model_id: str, name: str, input_price: float, output_price: float) -> ModelManageInfo:
    return ModelManageInfo(
        ai_model_id=model_id,
        ai_model_name=name,
        com_name="mock",
        com_url="https://mock.example/v1",
        api_key="k",
        is_using="1",
        async_type="async1",
        input_price_per_1m=input_price,
        output_price_per_1m=output_price,
        price_currency="USD",
    )


class HealthServiceTest(GatewayTestCase):
    async def test_cost_first_routing_and_circuit_breaker(self):
        async with AsyncSessionLocal() as db:
            db.add(_model("m-cheap", "cheap", 1, 2))
            db.add(_model("m-expensive", "expensive", 10, 20))
            await db.commit()

            await svc.update_routing_config(
                db, "async1",
                RoutingConfigUpdate(
                    strategy="cost_first",
                    retry_max=1,
                    failure_threshold=2,
                    cooldown_seconds=60,
                    output_ratio=0.3,
                    enabled=1,
                ),
            )
            models = [
                _model("m-cheap", "cheap", 1, 2),
                _model("m-expensive", "expensive", 10, 20),
            ]
            candidates = await svc.plan_candidates(db, models, "async1")
            self.assertEqual([m.ai_model_id for m in candidates], ["m-cheap", "m-expensive"])

            await svc.record_failure(
                db, "m-cheap", 100, "http_500", failure_threshold=2, cooldown_seconds=60,
            )
            await svc.record_failure(
                db, "m-cheap", 100, "http_500", failure_threshold=2, cooldown_seconds=60,
            )
            candidates = await svc.plan_candidates(db, models, "async1")
            self.assertEqual([m.ai_model_id for m in candidates], ["m-expensive"])

            overview = await svc.get_health_overview(db)
            cheap = next(c for c in overview["channels"] if c["modelId"] == "m-cheap")
            self.assertEqual(cheap["state"], "open")
            self.assertGreater(cheap["cooldownRemainingSeconds"], 0)

            await svc.reset_channel(db, "m-cheap")
            candidates = await svc.plan_candidates(db, models, "async1")
            self.assertEqual(candidates[0].ai_model_id, "m-cheap")

    async def test_all_channels_open_still_tries(self):
        async with AsyncSessionLocal() as db:
            db.add(_model("m1", "one", 1, 2))
            db.add(_model("m2", "two", 1, 2))
            await db.commit()
            await svc.update_routing_config(
                db, "async1",
                RoutingConfigUpdate(failure_threshold=1, cooldown_seconds=60),
            )
            await svc.record_failure(db, "m1", 10, "timeout", failure_threshold=1, cooldown_seconds=60)
            await svc.record_failure(db, "m2", 10, "timeout", failure_threshold=1, cooldown_seconds=60)
            models = [_model("m1", "one", 1, 2), _model("m2", "two", 1, 2)]
            candidates = await svc.plan_candidates(db, models, "async1")
            self.assertEqual(len(candidates), 2)

    async def test_success_updates_health_and_closes_circuit(self):
        async with AsyncSessionLocal() as db:
            db.add(_model("m1", "one", 1, 2))
            await db.commit()
            await svc.record_failure(
                db, "m1", 100, "http_500", failure_threshold=1, cooldown_seconds=60,
            )
            overview = await svc.get_health_overview(db)
            self.assertEqual(overview["channels"][0]["state"], "open")

            await svc.record_success(db, "m1", 50)
            overview = await svc.get_health_overview(db)
            channel = overview["channels"][0]
            self.assertEqual(channel["state"], "closed")
            self.assertEqual(channel["todaySuccess"], 1)
            self.assertEqual(channel["avgLatencyMs"], 50.0)
