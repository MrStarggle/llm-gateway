"""异步LLM总控 业务逻辑层

13 路异步LLM请求（async1..async13）的路由/参数配置：
- 种子数据 ASYNC_PURPOSE_SEED 与安卓端 ServerConfig.AsyncPurpose 常量一一对应，
  两端修改时务必同步（安卓端有 AsyncPurposeMappingTest 锁 purpose 格式）
- seed_async_manage_configs 只补缺失行（INSERT IGNORE 语义），不覆盖管理员已改字段
"""
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import AsyncSessionLocal
from app.models.async_manage_info import AsyncManageInfo
from app.schemas.async_manage import AsyncManageUpdate

logger = logging.getLogger(__name__)

# 13 路异步LLM请求注册表：(purpose, 中文名)
# 与安卓端 ServerConfig.AsyncPurpose 常量一一对应，顺序即管理页展示顺序
ASYNC_PURPOSE_SEED: list[tuple[str, str]] = [
    ("async1", "冒险正文摘要"),        # RACS summarizeReply
    ("async2", "老旧记忆总结"),        # RACS summarizeConversationMemory（自由文本，无 json 头）
    ("async3", "世界基础构建"),        # RACS extractWorldFoundation
    ("async4", "记忆摘要与条件任务"),  # RACS extractMemorySummary
    ("async5", "导演A·弧线方向"),      # RACS extractDirectorOutline
    ("async6", "导演B·剧情指导"),      # RACS extractDirectorPreview
    ("async7", "导演C·复盘"),          # RACS extractDirectorReview
    ("async8", "导演D·角色谋划"),      # RACS extractActorSchemes
    ("async9", "角色快照"),            # RACS extractCharacterSnapshot（自由文本，无 json 头）
    ("async10", "记忆索引"),           # RACS extractMemoryIndex
    ("async11", "世界状态对账"),       # RACS reconcileWorldState
    ("async12", "NPC对账"),            # RACS reconcileNpcInfo
    ("async13", "通用后台对话"),       # DeepSeekService（普通聊天/群聊/建议等）
]


async def seed_async_manage_configs() -> None:
    """启动时补齐 13 行种子配置（幂等，只插入缺失行，绝不覆盖管理员已改的字段）"""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(AsyncManageInfo.purpose))
            existing = set(result.scalars().all())
            added = []
            for purpose, name in ASYNC_PURPOSE_SEED:
                if purpose in existing:
                    continue
                db.add(AsyncManageInfo(
                    purpose=purpose,
                    request_name=name,
                    ai_model_id=None,
                    is_think="0",
                    temperature=None,
                    max_tokens=None,
                    is_using="0",
                    remarks=None,
                ))
                added.append(purpose)
            if added:
                await db.commit()
            logger.info(f"异步LLM总控种子检查完成: 共{len(ASYNC_PURPOSE_SEED)}路, 新增{added if added else '无'}")
        except Exception as e:
            await db.rollback()
            logger.warning(f"异步LLM总控种子写入失败（不阻塞启动）: {e}")


async def get_config_by_purpose(db: AsyncSession, purpose: str) -> AsyncManageInfo | None:
    """按 purpose 获取单路配置"""
    stmt = select(AsyncManageInfo).where(AsyncManageInfo.purpose == purpose)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_config_list(db: AsyncSession) -> list[AsyncManageInfo]:
    """获取全部配置（按 purpose 数字序 async1..async13 排序；字典序会把 async10 排到 async2 前）"""
    stmt = select(AsyncManageInfo)
    result = await db.execute(stmt)
    configs = list(result.scalars().all())
    configs.sort(key=lambda c: int(c.purpose[5:]))
    return configs


async def update_config(db: AsyncSession, purpose: str, data: AsyncManageUpdate) -> AsyncManageInfo | None:
    """更新配置（部分更新，只修改传入的字段）；purpose 不存在返回 None"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return await get_config_by_purpose(db, purpose)

    # 空串绑定归一为 NULL（清空绑定 → 回落轮询），避免空串/NULL 两种「未配置」状态
    if update_data.get("ai_model_id") == "":
        update_data["ai_model_id"] = None
    update_data["updated_at"] = datetime.now()

    stmt = (
        update(AsyncManageInfo)
        .where(AsyncManageInfo.purpose == purpose)
        .values(**update_data)
    )
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        logger.warning(f"更新异步LLM总控失败（purpose 不存在）: {purpose}")
        return None

    logger.info(f"更新异步LLM总控: purpose={purpose} fields={list(update_data.keys())}")
    return await get_config_by_purpose(db, purpose)
