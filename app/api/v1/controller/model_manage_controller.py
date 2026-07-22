"""模型管理 控制器"""
import logging
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.schemas.model_manage import ModelManageCreate, ModelManageUpdate, ModelManageQuery
from app.services import model_manage_service
from app.utils.response import ResponseFactory
from app.utils.admin_auth import verify_admin_token
from app.api.v1.controller.call_manage_controller import (
    _fetch_models_from_upstream,
    FetchModelsBody as FetchModelsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_admin_token)])

# companlist.txt 文件路径
_companlist_path = Path(__file__).parent.parent.parent.parent.parent / "companlist.txt"


def _read_companies() -> list[dict]:
    """读取厂家列表文件"""
    companies = []
    if not _companlist_path.exists():
        return companies
    with open(_companlist_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(",", 2)
                if len(parts) >= 2:
                    companies.append({
                        "domain": parts[0].strip(),
                        "name": parts[1].strip(),
                        "notes": parts[2].strip() if len(parts) > 2 else "",
                    })
    return companies


def _fuzzy_match(query: str, target: str) -> float:
    """计算两个字符串的模糊匹配度（0~1）"""
    return SequenceMatcher(None, query.lower(), target.lower()).ratio()


@router.get("/company-search")
async def search_company(name: str = ""):
    """
    根据厂家名称模糊搜索，返回匹配的厂家信息（URL 等）
    用于前端输入运营商名称时自动填充 URL
    name 为空时返回全部厂商列表
    """
    companies = _read_companies()

    # 空查询返回全部
    if not name or len(name) < 2:
        return ResponseFactory.ok(data={"matches": companies}, message="查询成功")

    scored = []
    for c in companies:
        # 综合名称和域名进行匹配
        name_score = _fuzzy_match(name, c["name"])
        domain_score = _fuzzy_match(name, c["domain"])
        # 子串匹配加成
        bonus = 0.2 if name.lower() in c["name"].lower() or name.lower() in c["domain"].lower() else 0
        score = max(name_score, domain_score) + bonus
        if score >= 0.4:
            scored.append({"company": c, "score": round(min(score, 1.0), 2)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    matches = [s["company"] for s in scored[:5]]  # 最多返回5条
    return ResponseFactory.ok(data={"matches": matches}, message="查询成功")


@router.post("/fetch-models")
async def fetch_models(body: FetchModelsRequest):
    """
    从运营商 API 拉取可用模型列表
    POST body: { com_url, api_key }
    """
    models, error = await _fetch_models_from_upstream(body.com_url, body.api_key)

    if not models and error:
        return ResponseFactory.bad_request(message=f"获取模型列表失败: {error}")

    models = sorted(set(models))
    return ResponseFactory.ok(data={"models": models}, message="查询成功")


# ==================== 模型 CRUD ====================


@router.get("/list")
async def list_models(
        query: ModelManageQuery = Depends(),
        db: AsyncSession = Depends(get_db),
):
    """获取模型列表（支持多条件筛选）"""
    models = await model_manage_service.get_model_list(db, query)
    total = await model_manage_service.get_model_count(db)
    return ResponseFactory.ok(
        data={"list": models, "total": total},
        message="查询成功",
    )


@router.get("/{model_id}")
async def get_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """根据 ID 获取模型详情"""
    model = await model_manage_service.get_model_by_id(db, model_id)
    if not model:
        return ResponseFactory.not_found(message="模型不存在")
    return ResponseFactory.ok(data=model, message="查询成功")


@router.post("/")
async def create_model(data: ModelManageCreate, db: AsyncSession = Depends(get_db)):
    """新增模型"""
    model = await model_manage_service.create_model(db, data)
    return ResponseFactory.created(data=model, message="新增成功")


@router.put("/{model_id}")
async def update_model(model_id: str, data: ModelManageUpdate, db: AsyncSession = Depends(get_db)):
    """更新模型（部分更新）—— 服务层为单一真实来源，不存在则返回 404"""
    model = await model_manage_service.update_model(db, model_id, data)
    if not model:
        return ResponseFactory.not_found(message="模型不存在")
    return ResponseFactory.ok(data=model, message="更新成功")


@router.delete("/{model_id}")
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """删除模型"""
    deleted = await model_manage_service.delete_model(db, model_id)
    if not deleted:
        return ResponseFactory.not_found(message="模型不存在")
    return ResponseFactory.ok(message="删除成功")
