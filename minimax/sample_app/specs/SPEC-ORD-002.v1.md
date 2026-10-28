---
spec_id: SPEC-ORD-002
revision: 1
status: active
effective_from: 2026-11-01
tags: [pricing, discount]
---

# SPEC-ORD-002 · 计价不变量（revision 1）

## 1. 目的

本规格不定义任何折扣业务规则，只定义 `ordercore` 计价结果必须始终成立的 **不变量**。
它独立于 SPEC-ORD-001 的版本变更：无论 revision 1 还是 revision 2，
以下条款都必须成立，且是回归测试的判定依据。

## 2. 不变量

### I1 金额一律整数分

- 所有金额参数与返回值都是 `int`，单位为「分」；
- 计算过程只用整数运算，不得出现 `float`、`Decimal` 或字符串金额；
- 百分比折扣向下取整（丢弃不足 1 分的部分）。

### I2 总价下限 0

`final_price_cents(...) >= 0` 对任意输入成立；
即使折扣与优惠券之和超过订单金额，也必须夹到 `0`，绝不返回负数。

### I3 优惠券不超过订单金额

`coupon_discount_cents(amount, coupon) <= amount`；
券面额大于当前应付金额时，最多把金额扣到 `0`。

### I4 空订单为 0

`items` 为空时：`subtotal_cents([]) == 0` 且 `final_price_cents([], customer) == 0`，
不得因运费或其他附加费产生正数金额。

## 3. 验收与测试映射

| 不变量 | 测试 |
| --- | --- |
| I1 整数分 | `test_final_price_is_integer_cents`、`test_member_discount_floors_to_whole_cents` |
| I2 总价非负 | `test_final_price_never_goes_negative` |
| I3 券不超订单金额 | `test_coupon_discount_capped_by_amount` |
| I4 空订单为 0 | `test_subtotal_of_empty_order_is_zero`、`test_final_price_of_empty_order_is_zero` |

以上用例全部位于 `tests/test_pricing_regression.py`，在 SPEC-ORD-001 的 v1 → v2 改造前后都必须通过。

## 4. 变更记录

- revision 1：首次发布四条不变量。