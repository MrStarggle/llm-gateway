"""会员等级配置（与 StarggleCom 保持一致，用于 LLM 转发的日限额校验）

积分制：余额即等级，随余额实时浮动，无到期时间。
- <100   免费会员 (free)
- >=100  白银会员 (silver)
- >=1000 黄金会员 (gold)
- >=5000 钻石会员 (diamond)

注意：改这里请同步改 StarggleCom/app/config/membership.py。
"""
from typing import Dict, Any, List

# 积分等级门槛（按 minBalance 从高到低匹配）
POINT_TIERS: List[Dict[str, Any]] = [
    {"level": "diamond", "levelName": "钻石会员", "minBalance": 5000},
    {"level": "gold", "levelName": "黄金会员", "minBalance": 1000},
    {"level": "silver", "levelName": "白银会员", "minBalance": 100},
    {"level": "free", "levelName": "免费会员", "minBalance": 0},
]

# 会员等级配置（dailyLimit 供转发侧每日限额校验沿用，额度后续按运营数据调整）
MEMBERSHIP_TIERS: Dict[str, Dict[str, Any]] = {
    "free": {
        "level": "free",
        "levelName": "免费会员",
        "dailyLimit": 10,
        "minBalance": 0,
    },
    "silver": {
        "level": "silver",
        "levelName": "白银会员",
        "dailyLimit": 100,
        "minBalance": 100,
    },
    "gold": {
        "level": "gold",
        "levelName": "黄金会员",
        "dailyLimit": 1000,
        "minBalance": 1000,
    },
    "diamond": {
        "level": "diamond",
        "levelName": "钻石会员",
        "dailyLimit": 5000,
        "minBalance": 5000,
    },
}

# 默认等级（未注册/未知等级统一回落）
DEFAULT_LEVEL = "free"

# 付费等级（余额达到对应门槛即为付费档）
PAID_LEVELS = ("silver", "gold", "diamond")


def tier_of_balance(balance: Any) -> Dict[str, Any]:
    """根据积分余额返回等级配置（负数/非数余额一律按 0 处理）"""
    try:
        balance = int(balance or 0)
    except (TypeError, ValueError):
        balance = 0
    for tier in POINT_TIERS:
        if balance >= tier["minBalance"]:
            return tier
    return MEMBERSHIP_TIERS[DEFAULT_LEVEL]


def get_tier(level: str) -> Dict[str, Any]:
    """获取等级配置，未知等级回落到免费档"""
    return MEMBERSHIP_TIERS.get(level, MEMBERSHIP_TIERS[DEFAULT_LEVEL])
