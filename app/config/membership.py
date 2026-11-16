"""会员等级配置（仅展示用，与 StarggleCom 保持一致）

计费已改为按次扣钻石（见 billing_service），会员等级不再参与限额校验：
- 余额 < 1000：普通会员（free）
- 余额 >= 1000：高级会员（senior）

注意：改这里请同步改 StarggleCom/app/config/membership.py。
"""
from typing import Any, Dict, List

# 等级门槛（按 minBalance 从高到低匹配）
POINT_TIERS: List[Dict[str, Any]] = [
    {"level": "senior", "levelName": "高级会员", "minBalance": 1000},
    {"level": "free", "levelName": "普通会员", "minBalance": 0},
]

# 等级配置（dailyLimit 已退役，恒为 0=不限；保留字段兼容既有接口消费方）
MEMBERSHIP_TIERS: Dict[str, Dict[str, Any]] = {
    "senior": {
        "level": "senior",
        "levelName": "高级会员",
        "dailyLimit": 0,
        "minBalance": 1000,
    },
    "free": {
        "level": "free",
        "levelName": "普通会员",
        "dailyLimit": 0,
        "minBalance": 0,
    },
}

# 默认等级（未注册/未知等级统一回落）
DEFAULT_LEVEL = "free"

# 付费等级（余额达到对应门槛即为付费档）
PAID_LEVELS = ("senior",)


def tier_of_balance(balance: Any) -> Dict[str, Any]:
    """根据余额返回等级配置（负数/非数余额一律按 0 处理）"""
    try:
        balance = int(balance or 0)
    except (TypeError, ValueError):
        balance = 0
    for tier in POINT_TIERS:
        if balance >= tier["minBalance"]:
            return tier
    return MEMBERSHIP_TIERS[DEFAULT_LEVEL]


def get_tier(level: str) -> Dict[str, Any]:
    """获取等级配置，未知等级回落到普通会员"""
    return MEMBERSHIP_TIERS.get(level, MEMBERSHIP_TIERS[DEFAULT_LEVEL])
