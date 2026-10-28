---
spec_id: SPEC-ORD-001
revision: 2
status: active
effective_from: 2026-11-01
tags: [pricing, discount]
---

# SPEC-ORD-001 · 订单计价规则（revision 2）

## 1. 生效说明

本 revision 自 **2026-11-01** 起生效，取代 revision 1。
生效后 `ordercore` 的计价必须按本文件执行；revision 1 的规则仅在历史订单回放时保留。

## 2. 变更摘要（相对 revision 1）

| 编号 | 变更 | 影响函数 |
| --- | --- | --- |
| C1 | **取消满 3 件 95 折**（体积折扣不再参与计价，恒为 0） | `volume_discount_cents` |
| C2 | **gold 会员满 3 件额外减 500 分**（忠诚奖励） | `loyalty_bonus_cents` |
| C3 | 新增运费：**满 5 件免运费**，未满 5 件按区域收 **east 800 分、west 1200 分** | `shipping_fee_cents` |
| C4 | 计算顺序调整为：会员折扣 → 优惠券 → gold 奖励 → 运费 | `final_price_cents` |
| C5 | 金额仍为整数分、总价下限 0、优惠券不超订单金额（沿用 revision 1 的不变量） | 全部 |

一句话概括：**取消满 3 件 95 折**，改为按会员等级与件数发放奖励并引入按区域计费的运费。

## 3. 规则明细

### R1 小计

`subtotal_cents(items) = Σ(unit_price_cents × qty)`；空明细为 `0`。金额一律整数分。

### R2 会员折扣

`member_discount_cents(amount, tier)`，按百分比向下取整：`basic` 0%、`silver` 3%、`gold` 5%。

### R3 体积折扣 —— 已取消

**取消满 3 件 95 折**：自 2026-11-01 起，件数不再触发任何百分比体积折扣，
`volume_discount_cents(...)` 对所有件数恒返回 `0`（保留函数以兼容既有调用方）。

### R4 优惠券

未达 `coupon.min_spend_cents` 返回 `0`；否则返回 `min(coupon.amount_cents, 当前应付金额)`。
门槛按 **会员折扣之后** 的当前应付金额判定（见 R6 的计算顺序）。

### R5 gold 忠诚奖励

`loyalty_bonus_cents(customer, item_count)`：**gold 会员满 3 件额外减 500 分**；
即 `customer.tier == "gold"` 且 `item_count >= 3` 时返回 `500`，其余情况（含 silver/basic、件数不足 3）返回 `0`。
该奖励为固定金额，不随订单金额变化，且不与会员折扣冲突（两者可叠加）。

### R6 运费

`shipping_fee_cents(...)`：

- **满 5 件免运费**（件数 `>= 5` 时运费为 `0`）；
- 未满 5 件按区域收费：**east 800 分、west 1200 分**；
- 空订单（件数为 0）运费为 `0`，以保证 SPEC-ORD-002 的「空订单总价为 0」。

> 实现提示：免运费判断依赖件数，而 revision 1 的签名只有 `(amount_cents, region)`；
> 允许在改造中为该函数追加件数参数，并由 `final_price_cents` 传入。

### R7 计算顺序与总价

`final_price_cents(items, customer, coupon=None)` 必须严格按以下顺序：

1. 小计；
2. 减会员折扣（按小计金额）；
3. 减优惠券（门槛按会员折扣后的金额判定，且不超过该金额）；
4. 减 gold 奖励（500 分，满足 R5 条件时）；
5. 加运费（按 R6 与件数、区域）；
6. 取 `max(0, 金额)`，保证总价非负。

顺序是有语义的：优惠券门槛必须在 **会员折扣之后** 判定，
因此「先算券、后算会员折扣」或「按小计判定门槛」都视为不符合本规格。

## 4. 计算示例

以 `east` 区域、无优惠券为例：

| 场景 | 计算 | 总价 |
| --- | --- | --- |
| gold，3 件 × 2000 | 6000 − 300(会员) − 0(券) − 500(奖励) + 800(运费) | **6000** |
| basic，4 件 × 1000 | 4000 − 0 − 0 − 0 + 800 | **4800** |
| basic，4 件 × 1000（west） | 4000 − 0 − 0 − 0 + 1200 | **5200** |
| basic，5 件 × 1000 | 5000 − 0 − 0 − 0 + 0（包邮） | **5000** |
| gold，3 件 × 2000，券(500, 门槛 5000) | 6000 − 300 − 500 − 500 + 800 | **5500** |

## 5. 不变量（不变）

- 金额为整数分，折扣向下取整；
- 总价 `>= 0`；
- 优惠券折扣不超过订单金额；
- 空订单总价为 `0`（不因运费变成正数）。

## 6. 验收与测试映射

| 变更 | 测试 |
| --- | --- |
| C1 取消 95 折 | `tests/test_pricing_target.py::test_basic_member_no_longer_gets_95_percent_at_three_items`、`test_volume_discount_is_gone_for_large_basic_order` |
| C2 gold 奖励 500 | `test_gold_member_with_three_items_gets_extra_500_off`、`test_gold_bonus_requires_three_items`、`test_gold_bonus_requires_gold_tier` |
| C3 运费 / 包邮 | `test_five_items_ship_free_east`、`test_five_items_ship_free_west`、`test_four_items_east_pays_800`、`test_four_items_west_pays_1200` |
| C4 计算顺序 | `test_coupon_threshold_is_checked_after_member_discount`、`test_coupon_applies_when_threshold_matches_post_discount_amount` |
| 组合场景 | `test_gold_three_items_with_coupon_combo`、`test_gold_three_items_with_coupon_combo_west`、`test_gold_bonus_with_fractional_member_discount`、`test_total_floor_still_applies_after_shipping` |

改造后 `tests/test_pricing_regression.py` 必须继续全绿。

## 7. 变更记录

- revision 1：会员折扣 + 满 3 件 95 折 + 优惠券 + 总价非负。
- revision 2：取消满 3 件 95 折；gold 满 3 件额外减 500 分；满 5 件免运费、否则 east 800 / west 1200；
  计算顺序改为会员折扣 → 优惠券 → gold 奖励 → 运费。