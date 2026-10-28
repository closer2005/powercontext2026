"""ordercore 计价规则（SPEC-ORD-001）。

本文件是基线实现，对应 **SPEC-ORD-001 revision 1**（v1）：

* 会员折扣：silver 3%（向下取整）、gold 5%（向下取整）、basic 0%；
* 体积折扣：订单件数 >= 3 时，按当前金额的 5% 折扣（向下取整）；
* 优惠券：达到门槛后生效，且不超过当前应付金额；
* 运费：v1 不收运费，固定 0；
* 总价下限 0，金额一律整数分。

**v2（revision 2，2026-11-01 生效）尚未实现。**
``loyalty_bonus_cents`` 与 ``shipping_fee_cents`` 是 v2 预留的接入点，
基线固定返回 0；``volume_discount_cents`` 在 v2 中需要被取消。
``final_price_cents`` 把四类调整按固定顺序串起来，改造时应保持其结构：
去掉一处、加上两处即可，不需要重写函数体。
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .models import Coupon, Customer, Item

__all__ = [
    "subtotal_cents",
    "member_discount_cents",
    "coupon_discount_cents",
    "volume_discount_cents",
    "loyalty_bonus_cents",
    "shipping_fee_cents",
    "final_price_cents",
]

#: 会员等级 -> 折扣百分比（整百分比，避免浮点）
_MEMBER_DISCOUNT_PERCENT = {"basic": 0, "silver": 3, "gold": 5}

#: v1 体积折扣：百分比与件数门槛
_VOLUME_DISCOUNT_PERCENT = 5
_VOLUME_DISCOUNT_MIN_ITEMS = 3


def _percent_floor(amount_cents: int, percent: int) -> int:
    """按百分比向下取整返回整数分，全程整数运算。"""
    return (amount_cents * percent) // 100


def _item_lines(items: Iterable[Item]) -> List[Item]:
    return list(items)


def _item_count(items: Iterable[Item]) -> int:
    """件数定义：所有明细的 ``qty`` 之和（不是明细行数）。"""
    return sum(item.qty for item in items)


def subtotal_cents(items: Iterable[Item]) -> int:
    """订单小计（分）：各行 ``unit_price_cents * qty`` 之和。空明细返回 0。"""
    return sum(item.unit_price_cents * item.qty for item in items)


def member_discount_cents(amount_cents: int, tier: str) -> int:
    """会员折扣（分）：silver 3%、gold 5%、basic 0%，向下取整。"""
    if tier not in _MEMBER_DISCOUNT_PERCENT:
        raise ValueError(f"未知会员等级: {tier!r}")
    return _percent_floor(amount_cents, _MEMBER_DISCOUNT_PERCENT[tier])


def coupon_discount_cents(amount_cents: int, coupon: Optional[Coupon]) -> int:
    """优惠券折扣（分）。

    未达 ``coupon.min_spend_cents`` 返回 0；否则取 ``min(coupon.amount_cents, amount_cents)``，
    保证券不会把金额扣成负数。
    """
    if coupon is None:
        return 0
    if amount_cents < coupon.min_spend_cents:
        return 0
    return min(coupon.amount_cents, amount_cents)


def volume_discount_cents(amount_cents: int, item_count: int) -> int:
    """体积折扣（分）——**v1 规则**：件数 >= 3 时按 5% 折扣，向下取整。

    SPEC-ORD-001 revision 2 自 2026-11-01 起取消本规则（恒为 0）。
    """
    if item_count >= _VOLUME_DISCOUNT_MIN_ITEMS:
        return _percent_floor(amount_cents, _VOLUME_DISCOUNT_PERCENT)
    return 0


def loyalty_bonus_cents(customer: Customer, item_count: int) -> int:
    """忠诚奖励（分）——**v2 待实现**，基线固定返回 0。

    v2 规则（SPEC-ORD-001 rev 2）：``customer.tier == "gold"`` 且
    ``item_count >= 3`` 时，额外减免 500 分；其余情况为 0。
    保留参数与返回类型，使调用方可以在不改签名的情况下替换实现。
    """
    return 0


def shipping_fee_cents(amount_cents: int, region: str) -> int:
    """运费（分）——**v2 待实现**，基线固定返回 0（v1 不收运费）。

    v2 规则（SPEC-ORD-001 rev 2）：满 5 件免运费；未满 5 件按区域收费，
    east 800 分、west 1200 分。空订单仍为 0（SPEC-ORD-002 不变量优先）。

    注意：v2 的免运费判断依赖「件数」，而本基线签名只有金额与区域。
    改造时可以扩展签名（例如追加 ``item_count`` 参数并由
    ``final_price_cents`` 传入），这属于任务允许的局部替换。
    """
    return 0


def final_price_cents(items: Iterable[Item], customer: Customer, coupon: Optional[Coupon] = None) -> int:
    """订单最终应付金额（分）。

    v1 计算顺序（本基线）：
    ``小计 → 减会员折扣 → 减体积折扣 → 减优惠券 → 加运费 → 下限 0``。

    v2 计算顺序（待实现）：
    ``小计 → 减会员折扣 → 减优惠券 → 减 gold 奖励 → 加运费 → 下限 0``。

    每一步都通过上面的独立函数完成，因此「去掉体积折扣、改用 gold 奖励、
    加上运费」应当只改动本函数中的两三行，而不触碰小计与会员折扣逻辑。
    优惠券门槛按调用时刻的「当前应付金额」判定，所以顺序会影响结果。
    """
    lines = _item_lines(items)
    item_count = _item_count(lines)

    amount = subtotal_cents(lines)
    amount -= member_discount_cents(amount, customer.tier)
    amount -= volume_discount_cents(amount, item_count)
    amount -= coupon_discount_cents(amount, coupon)
    amount += shipping_fee_cents(amount, customer.region)
    return max(0, amount)