"""模型管理排序测试：复制模型沿用源批次，重新查询仍紧跟源记录"""
# 必须先导入 tests.base：它在导入 app 之前设置独立测试数据库
from tests.base import GatewayTestCase
from app.config.database import AsyncSessionLocal
from app.schemas.model_manage import ModelManageCreate, ModelManageQuery
from app.services import model_manage_service as svc


def _model_payload(**overrides) -> ModelManageCreate:
    data = {
        "ai_model_name": "gpt-4o",
        "com_name": "test-provider",
        "com_url": "https://example.com/v1",
        "api_key": "sk-test",
        "is_using": "1",
    }
    data.update(overrides)
    return ModelManageCreate(**data)


class ModelManageSortTest(GatewayTestCase):
    async def test_copy_inherits_batch_and_stays_below_source(self):
        async with AsyncSessionLocal() as db:
            old = await svc.create_model(db, _model_payload(batch_no=1000))
            newer = await svc.create_model(
                db, _model_payload(ai_model_name="gpt-4.1", batch_no=2000),
            )
            copied = await svc.create_model(
                db, _model_payload(batch_no=old.batch_no),
            )

            models = await svc.get_model_list(db, ModelManageQuery())
            self.assertEqual(
                [m.ai_model_id for m in models],
                [newer.ai_model_id, old.ai_model_id, copied.ai_model_id],
            )

    async def test_new_model_gets_new_batch(self):
        async with AsyncSessionLocal() as db:
            first = await svc.create_model(db, _model_payload())
            second = await svc.create_model(db, _model_payload(ai_model_name="gpt-4.1"))

            self.assertIsNotNone(first.batch_no)
            self.assertIsNotNone(second.batch_no)
            self.assertLessEqual(first.batch_no, second.batch_no)
