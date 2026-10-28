"""目标测试 —— SPEC-ORD-001 revision 2（2026-11-01 生效）。

现状：基线实现是 revision 1，本文件预期 **全部失败**（AssertionError），
改造完成后必须 **全部通过**。

v2 规则（见 ``specs/SPEC-ORD-001.v2.md``）：

1. 取消满 3 件 95 折（``volume_discount_cents`` 不再参与最终价）；
2. gold 会员且订单满 3 件，额外减 500 分；
3. 满 5 件免运费，未满 5 件：east 800 分 / west 1200 分；
4. 计算顺序：会员折扣 → 优惠券 → gold 奖励 → 运费；
5. 金额仍为整数分、总价下限 0。

所有断言都落在公开函数 ``final_price_cents`` 上，不依赖内部实现细节。
件数 = 所有明细 ``qty`` 之和。
"""

from __future__ import annotations

from ordercore.pricing import final_price_cents

from conftest import make_coupon, make_customer, make_item, make_items


def _total(items, tier="basic", region="east", coupon=None) -> int:
    return final_price_cents(items, make_customer(tier=tier, region=region), coupon)


# --- v2-1 / v2-2：gold 满 3 件额外减 500 分 ---------------------------------


def test_gold_member_with_three_items_gets_extra_500_off():
    """gold + 3 件：3000 - 150(会员) - 500(奖励) + 800(运费 east) = 3150。"""
    items = make_items(3, unit_price_cents=1000)  # 小计 3000
    assert _total(items, tier="gold", region="east") == 3150


def test_gold_bonus_requires_three_items():
    """只有 2 件时 gold 奖励不生效：2000 - 100(会员) + 800(运费) = 2700。"""
    items = make_items(2, unit_price_cents=1000)
    assert _total(items, tier="gold", region="east") == 2700


def test_gold_bonus_requires_gold_tier():
    """silver 满 3 件没有 500 分奖励：3000 - 90(会员) + 800(运费) = 3710。"""
    items = make_items(3, unit_price_cents=1000)
    assert _total(items, tier="silver", region="east") == 3710


# --- v2-1：取消满 3 件 95 折 ------------------------------------------------


def test_basic_member_no_longer_gets_95_percent_at_three_items():
    """basic + 3 件：3000 不打 95 折，只加运费 800 = 3800。

    v1 基线此处为 2850（3000 - 150 体积折扣），改造后应为 3800。
    """
    items = make_items(3, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 3800


def test_volume_discount_is_gone_for_large_basic_order():
    """basic + 6 件（小计 6000）：不再有 5% 体积折扣，且免运费 = 6000。"""
    items = make_items(6, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 6000


# --- v2-3：运费与满 5 件包邮 ------------------------------------------------


def test_five_items_ship_free_east():
    """满 5 件免运费：basic + 5 件，east，5000 原价不动。"""
    items = make_items(5, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 5000


def test_five_items_ship_free_west():
    """满 5 件免运费（west 同样免）。"""
    items = make_items(5, unit_price_cents=1000)
    assert _total(items, tier="basic", region="west") == 5000


def test_four_items_east_pays_800():
    """4 件未满 5：east 收 800 分，4000 + 800 = 4800。"""
    items = make_items(4, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 4800


def test_four_items_west_pays_1200():
    """4 件未满 5：west 收 1200 分，4000 + 1200 = 5200。"""
    items = make_items(4, unit_price_cents=1000)
    assert _total(items, tier="basic", region="west") == 5200


# --- v2-4：计算顺序（优惠券门槛按会员折扣后的金额判定） ---------------------


def test_coupon_threshold_is_checked_after_member_discount():
    """silver + 3 件（小计 3000）+ 券(200, 门槛 2950)。

    会员折扣后金额 = 2910 < 2950，券不生效：
    3000 - 90 + 800 = 3710。若按小计 3000 判定门槛会错误地得到 3510。
    """
    items = make_items(3, unit_price_cents=1000)
    coupon = make_coupon(amount_cents=200, min_spend_cents=2950)
    assert _total(items, tier="silver", region="east", coupon=coupon) == 3710


def test_coupon_applies_when_threshold_matches_post_discount_amount():
    """silver + 3 件 + 券(200, 门槛 2910)：门槛恰好等于会员折扣后金额，券生效。

    3000 - 90 - 200 + 800 = 3510。
    """
    items = make_items(3, unit_price_cents=1000)
    coupon = make_coupon(amount_cents=200, min_spend_cents=2910)
    assert _total(items, tier="silver", region="east", coupon=coupon) == 3510


# --- 组合：gold 满 3 件 + 优惠券 -------------------------------------------


def test_gold_three_items_with_coupon_combo():
    """gold + 3 件单价 2000 + 券(500, 门槛 5000)，east。

    6000 - 300(会员 5%) = 5700
         - 500(券，5700 >= 5000) = 5200
         - 500(gold 奖励)          = 4700
         + 800(运费)               = 5500
    """
    items = make_items(3, unit_price_cents=2000)
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert _total(items, tier="gold", region="east", coupon=coupon) == 5500


def test_gold_three_items_with_coupon_combo_west():
    """同上但 west：运费 1200，顺序不变 → 4700 + 1200 = 5900。"""
    items = make_items(3, unit_price_cents=2000)
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert _total(items, tier="gold", region="west", coupon=coupon) == 5900


def test_gold_bonus_with_fractional_member_discount():
    """999 分订单：会员折扣向下取整 49，再减 500，再加快递 800 = 1250。"""
    items = [make_item(unit_price_cents=333, qty=3)]  # 小计 999
    assert _total(items, tier="gold", region="east") == 1250


def test_total_floor_still_applies_after_shipping():
    """券把金额扣到 0 后再加运费，总价仍非负且等于运费。

    basic + 1 件 500 + 券(100000, 门槛 0)：max(0, 500-500) + 800 = 800。
    """
    items = [make_item(unit_price_cents=500, qty=1)]
    coupon = make_coupon(amount_cents=100000, min_spend_cents=0)
    assert _total(items, tier="basic", region="east", coupon=coupon) == 800