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
    """体积折扣（分）：SPEC-ORD-001 revision 2 已取消体积折扣，恒为 0。"""
    return 0


def loyalty_bonus_cents(customer: Customer, item_count: int) -> int:
    """gold 会员满 3 件额外减免 500 分，其余情况为 0。"""
    if customer.tier == "gold" and item_count >= 3:
        return 500
    return 0


def shipping_fee_cents(amount_cents: int, region: str, item_count: int = 0) -> int:
    """运费（分）：满 5 件免运费，未满 5 件按区域收费。

    east 收 800 分，west 收 1200 分；空订单不收运费。
    """
    if item_count == 0 or item_count >= 5:
        return 0
    if region == "east":
        return 800
    if region == "west":
        return 1200
    return 0


def final_price_cents(items: Iterable[Item], customer: Customer, coupon: Optional[Coupon] = None) -> int:
    """订单最终应付金额（分）。

    按 SPEC-ORD-001 revision 2 顺序计价：
    ``小计 → 减会员折扣 → 减优惠券 → 减 gold 奖励 → 加运费 → 下限 0``。

    优惠券门槛按会员折扣后的当前应付金额判定。
    """
    lines = _item_lines(items)
    item_count = _item_count(lines)

    amount = subtotal_cents(lines)
    amount -= member_discount_cents(amount, customer.tier)
    amount -= coupon_discount_cents(amount, coupon)
    amount -= loyalty_bonus_cents(customer, item_count)
    amount += shipping_fee_cents(amount, customer.region, item_count)
    return max(0, amount)