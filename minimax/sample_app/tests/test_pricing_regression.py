"""回归测试 —— SPEC-ORD-001 中「跨版本不变」的计价行为。

设计约束（很重要）：

* 这些用例必须在 v1 基线与 v2 改造后 **都通过**。
* 因此这里 **不断言 v1 的「满 3 件 5% 体积折扣」行为**（v2 会取消它），
  也不对非空订单的最终总价做「含/不含运费」的绝对值断言（v2 会加运费）。
* 精确数值断言只落在跨版本稳定的构件上：``subtotal_cents``、
  ``member_discount_cents``、``coupon_discount_cents``；
  对 ``final_price_cents`` 只断言不变量（空单为 0、非负、整数分）。
"""

from __future__ import annotations

from ordercore.models import Customer, Item
from ordercore.pricing import (
    coupon_discount_cents,
    final_price_cents,
    member_discount_cents,
    subtotal_cents,
)

from conftest import make_coupon, make_customer, make_item, make_items


# --- 小计 -------------------------------------------------------------------


def test_subtotal_sums_line_totals():
    """小计 = 各行 单价 × 数量 之和。"""
    items = [
        make_item(unit_price_cents=1999, qty=2),
        make_item(unit_price_cents=500, qty=5),
    ]
    assert subtotal_cents(items) == 1999 * 2 + 500 * 5 == 6498


def test_subtotal_of_empty_order_is_zero():
    """空明细小计为 0。"""
    assert subtotal_cents([]) == 0


def test_subtotal_of_single_item():
    """单行明细的小计。"""
    assert subtotal_cents([make_item(unit_price_cents=1250, qty=3)]) == 3750


# --- 会员折扣 ---------------------------------------------------------------


def test_silver_member_gets_three_percent_discount():
    assert member_discount_cents(10000, "silver") == 300


def test_gold_member_gets_five_percent_discount():
    assert member_discount_cents(10000, "gold") == 500


def test_basic_member_has_no_discount():
    assert member_discount_cents(10000, "basic") == 0
    assert member_discount_cents(1, "basic") == 0


def test_member_discount_floors_to_whole_cents():
    """折扣向下取整，且结果始终是 int（不引入浮点分）。"""
    silver = member_discount_cents(999, "silver")  # 29.97 -> 29
    gold = member_discount_cents(999, "gold")  # 49.95 -> 49
    assert silver == 29
    assert gold == 49
    assert isinstance(silver, int) and not isinstance(silver, bool)
    assert isinstance(gold, int) and not isinstance(gold, bool)


# --- 优惠券 -----------------------------------------------------------------


def test_coupon_below_min_spend_yields_nothing():
    """未达门槛：券不打折。"""
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert coupon_discount_cents(4999, coupon) == 0


def test_coupon_discount_capped_by_amount():
    """券面额大于应付金额时，只扣到 0，不产生负金额。"""
    coupon = make_coupon(amount_cents=1000, min_spend_cents=0)
    assert coupon_discount_cents(300, coupon) == 300


def test_coupon_at_exact_min_spend_applies():
    """金额恰好等于门槛时券生效。"""
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert coupon_discount_cents(5000, coupon) == 500


# --- 最终总价：只断言不变量 -------------------------------------------------


def test_final_price_of_empty_order_is_zero():
    """空订单最终价为 0（SPEC-ORD-002 不变量）。"""
    customer = make_customer(tier="gold", region="west")
    assert final_price_cents([], customer) == 0
    assert final_price_cents([], customer, make_coupon(100, 0)) == 0


def test_final_price_never_goes_negative():
    """券面额远大于订单金额时，总价被夹到 0 而非负数。"""
    customer = make_customer(tier="basic", region="east")
    items = [make_item(unit_price_cents=500, qty=1)]
    coupon = make_coupon(amount_cents=100000, min_spend_cents=0)
    assert final_price_cents(items, customer, coupon) >= 0


def test_final_price_is_integer_cents():
    """最终价必须是 int（整数分），不是 float / Decimal。"""
    customer = make_customer(tier="silver", region="east")
    items = [make_item(unit_price_cents=1234, qty=1)]
    total = final_price_cents(items, customer, make_coupon(amount_cents=99, min_spend_cents=0))
    assert isinstance(total, int) and not isinstance(total, bool)


def test_coupon_never_increases_total():
    """同一订单加上一张达标券后，总价不会变高。"""
    customer = make_customer(tier="basic", region="east")
    items = [make_item(unit_price_cents=10000, qty=1)]
    coupon = make_coupon(amount_cents=1500, min_spend_cents=5000)
    assert final_price_cents(items, customer, coupon) < final_price_cents(items, customer)


def test_final_price_does_not_mutate_inputs():
    """计价是纯函数，不修改入参。"""
    items = [make_item(unit_price_cents=800, qty=2)]
    customer = Customer(customer_id="C-9", tier="gold", region="west")
    final_price_cents(items, customer, make_coupon(50, 0))
    assert items == [Item(name="widget", unit_price_cents=800, qty=2)]
    assert customer == Customer(customer_id="C-9", tier="gold", region="west")