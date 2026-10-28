---
spec_id: SPEC-ORD-001
revision: 1
status: active
effective_from: 2026-11-01
tags: [pricing, discount]
---

# SPEC-ORD-001 · 订单计价规则（revision 1）

## 1. 目的与范围

规定 `ordercore` 订单计价服务从「订单明细」到「最终应付金额」的全部规则。
适用于 `src/ordercore/pricing.py` 中的公开函数与 `final_price_cents` 的计算链路。
本文件描述 **revision 1（v1）** 的现行规则，是当前基线实现的依据。

## 2. 术语

- **金额**：一律为整数「分」（`int`），禁止浮点数参与计算，不得出现小数分。
- **小计（subtotal）**：所有明细的 `unit_price_cents × qty` 之和。
- **件数（item_count）**：所有明细 `qty` 之和（是件数，不是明细行数）。
- **向下取整**：百分比折扣计算结果只保留整数分，丢弃不足 1 分的部分（`amount * 百分比 // 100`）。

## 3. 规则

### R1 小计

`subtotal_cents(items) = Σ(unit_price_cents × qty)`；空明细小计为 `0`。

### R2 会员折扣

`member_discount_cents(amount, tier)`，按百分比向下取整：

| tier | 折扣 |
| --- | --- |
| `basic` | 0% |
| `silver` | 3% |
| `gold` | 5% |

### R3 体积折扣（满 3 件）

件数 `>= 3` 时，按 **当前金额** 的 5% 折扣，向下取整；否则为 0。
业务口径为：**订单满 3 件享 95 折**。

### R4 优惠券

`coupon_discount_cents(amount, coupon)`：

- 当前应付金额 `< coupon.min_spend_cents` 时，券不生效，折扣为 `0`；
- 否则折扣为 `min(coupon.amount_cents, amount)`，**券不得超过订单金额**。

### R5 运费

revision 1 不收运费，`shipping_fee_cents(...)` 恒返回 `0`。

### R6 总价

`final_price_cents(items, customer, coupon=None)` 按以下顺序计算，最后取 `max(0, 金额)`：

1. 小计；
2. 减会员折扣（按小计金额）；
3. 减体积折扣（按会员折扣后的金额）；
4. 减优惠券（门槛按体积折扣后的当前金额判定）；
5. 加运费（v1 为 0）；
6. 结果下限 0。

## 4. 不变量（与 SPEC-ORD-002 一致）

- 所有金额为整数分；
- 最终总价 `>= 0`；
- 优惠券折扣不超过订单金额；
- 空订单总价为 `0`。

## 5. 验收与测试映射

| 规则 | 测试 |
| --- | --- |
| R1 小计 | `tests/test_pricing_regression.py::test_subtotal_sums_line_totals` |
| R2 会员折扣 | `test_silver_member_gets_three_percent_discount`、`test_gold_member_gets_five_percent_discount`、`test_basic_member_has_no_discount` |
| R4 优惠券 | `test_coupon_below_min_spend_yields_nothing`、`test_coupon_discount_capped_by_amount` |
| R6 总价不变量 | `test_final_price_of_empty_order_is_zero`、`test_final_price_never_goes_negative` |

> 注：体积折扣（R3）属于 revision 1 的临时规则，它的具体数值 **不出现在回归测试的断言中**，
> 因为 revision 2 会取消该规则。回归测试只覆盖跨版本稳定的行为。

## 6. 变更记录

- revision 1：首次发布（会员折扣 + 满 3 件 95 折 + 优惠券）。
- revision 2（待发布）：见 `SPEC-ORD-001.v2.md`。