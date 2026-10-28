# MiniMax 请求原文（system + user）

## role: system

````text
你是一名资深 Python 工程师，在一个真实的软件仓库里工作。
用户会给你一个开发任务，以及该任务当前有效的规格（spec）、相关代码和测试。

工作要求：
1. 严格按规格实现，不要改动测试文件、规格文件或其他无关文件；
2. 修改后既有回归测试必须继续通过，目标测试必须转为通过；
3. 只输出一个统一的 unified diff（git apply 可应用），不要输出解释性正文；
4. diff 的文件路径以业务工程根目录为基准，形如 `--- a/src/ordercore/pricing.py` 和 `+++ b/src/ordercore/pricing.py`；
5. 如果你需要新增辅助函数或调整私有函数签名，允许，但必须保持公开函数的既有行为兼容（除非规格明确要求改变）。

````

## role: user

````text
## 开发任务
task_id: TASK-ORD-PRICING-V2
标题: 订单计价切换到 SPEC-ORD-001 v2 优惠与包邮规则
描述: 按 SPEC-ORD-001 v2（2026-11-01 生效）改造 ordercore 计价：取消满 3 件 95 折；gold 会员满 3 件额外减 500 分；满 5 件免运费，未满 5 件按区域收运费 east 800 分、west 1200 分；计算顺序为会员折扣→优惠券→gold 奖励→运费；保持金额整数分与总价非负。

## 当前有效规格（必须遵守）
### SPEC-ORD-001 revision 2  (specs/SPEC-ORD-001.v2.md)
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

### SPEC-ORD-002 revision 1  (specs/SPEC-ORD-002.v1.md)
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

## 相关代码（需要修改或阅读）
### src/ordercore/pricing.py::volume_discount_cents  (lines 81-88)
```python
def volume_discount_cents(amount_cents: int, item_count: int) -> int:
    """体积折扣（分）——**v1 规则**：件数 >= 3 时按 5% 折扣，向下取整。

    SPEC-ORD-001 revision 2 自 2026-11-01 起取消本规则（恒为 0）。
    """
    if item_count >= _VOLUME_DISCOUNT_MIN_ITEMS:
        return _percent_floor(amount_cents, _VOLUME_DISCOUNT_PERCENT)
    return 0
```

### src/ordercore/pricing.py::loyalty_bonus_cents  (lines 91-98)
```python
def loyalty_bonus_cents(customer: Customer, item_count: int) -> int:
    """忠诚奖励（分）——**v2 待实现**，基线固定返回 0。

    v2 规则（SPEC-ORD-001 rev 2）：``customer.tier == "gold"`` 且
    ``item_count >= 3`` 时，额外减免 500 分；其余情况为 0。
    保留参数与返回类型，使调用方可以在不改签名的情况下替换实现。
    """
    return 0
```

### src/ordercore/pricing.py::shipping_fee_cents  (lines 101-111)
```python
def shipping_fee_cents(amount_cents: int, region: str) -> int:
    """运费（分）——**v2 待实现**，基线固定返回 0（v1 不收运费）。

    v2 规则（SPEC-ORD-001 rev 2）：满 5 件免运费；未满 5 件按区域收费，
    east 800 分、west 1200 分。空订单仍为 0（SPEC-ORD-002 不变量优先）。

    注意：v2 的免运费判断依赖「件数」，而本基线签名只有金额与区域。
    改造时可以扩展签名（例如追加 ``item_count`` 参数并由
    ``final_price_cents`` 传入），这属于任务允许的局部替换。
    """
    return 0
```

### src/ordercore/pricing.py::final_price_cents  (lines 114-135)
```python
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
```

### src/ordercore/pricing.py::_percent_floor  (lines 42-44)
```python
def _percent_floor(amount_cents: int, percent: int) -> int:
    """按百分比向下取整返回整数分，全程整数运算。"""
    return (amount_cents * percent) // 100
```

### src/ordercore/pricing.py::_item_lines  (lines 47-48)
```python
def _item_lines(items: Iterable[Item]) -> List[Item]:
    return list(items)
```

### src/ordercore/pricing.py::_item_count  (lines 51-53)
```python
def _item_count(items: Iterable[Item]) -> int:
    """件数定义：所有明细的 ``qty`` 之和（不是明细行数）。"""
    return sum(item.qty for item in items)
```

### src/ordercore/pricing.py::subtotal_cents  (lines 56-58)
```python
def subtotal_cents(items: Iterable[Item]) -> int:
    """订单小计（分）：各行 ``unit_price_cents * qty`` 之和。空明细返回 0。"""
    return sum(item.unit_price_cents * item.qty for item in items)
```

### src/ordercore/pricing.py::member_discount_cents  (lines 61-65)
```python
def member_discount_cents(amount_cents: int, tier: str) -> int:
    """会员折扣（分）：silver 3%、gold 5%、basic 0%，向下取整。"""
    if tier not in _MEMBER_DISCOUNT_PERCENT:
        raise ValueError(f"未知会员等级: {tier!r}")
    return _percent_floor(amount_cents, _MEMBER_DISCOUNT_PERCENT[tier])
```

### src/ordercore/pricing.py::coupon_discount_cents  (lines 68-78)
```python
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
```

### src/ordercore/models.py::Item  (lines 17-37)
```python
class Item:
    """一条订单明细。"""

    name: str
    unit_price_cents: int
    qty: int

    def __post_init__(self) -> None:
        if not isinstance(self.unit_price_cents, int) or isinstance(self.unit_price_cents, bool):
            raise TypeError("unit_price_cents 必须是 int（整数分）")
        if not isinstance(self.qty, int) or isinstance(self.qty, bool):
            raise TypeError("qty 必须是 int")
        if self.unit_price_cents < 0:
            raise ValueError("unit_price_cents 不能为负")
        if self.qty < 0:
            raise ValueError("qty 不能为负")

    @property
    def line_total_cents(self) -> int:
        """本行金额（分）= 单价 × 数量。"""
        return self.unit_price_cents * self.qty
```

### src/ordercore/models.py::Customer  (lines 41-52)
```python
class Customer:
    """下单客户。"""

    customer_id: str
    tier: str
    region: str

    def __post_init__(self) -> None:
        if self.tier not in CUSTOMER_TIERS:
            raise ValueError(f"未知会员等级: {self.tier!r}，允许值 {CUSTOMER_TIERS}")
        if self.region not in REGIONS:
            raise ValueError(f"未知区域: {self.region!r}，允许值 {REGIONS}")
```

### src/ordercore/models.py::Coupon  (lines 56-71)
```python
class Coupon:
    """优惠券。``min_spend_cents`` 为使用门槛（以打折后的应付金额判定）。"""

    code: str
    amount_cents: int
    min_spend_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.amount_cents, int) or isinstance(self.amount_cents, bool):
            raise TypeError("amount_cents 必须是 int（整数分）")
        if not isinstance(self.min_spend_cents, int) or isinstance(self.min_spend_cents, bool):
            raise TypeError("min_spend_cents 必须是 int（整数分）")
        if self.amount_cents < 0:
            raise ValueError("amount_cents 不能为负")
        if self.min_spend_cents < 0:
            raise ValueError("min_spend_cents 不能为负")
```

## 验证测试
### 目标测试（当前应失败，修改后必须全部通过）
### tests/test_pricing_target.py::test_gold_member_with_three_items_gets_extra_500_off
```python
def test_gold_member_with_three_items_gets_extra_500_off():
    """gold + 3 件：3000 - 150(会员) - 500(奖励) + 800(运费 east) = 3150。"""
    items = make_items(3, unit_price_cents=1000)  # 小计 3000
    assert _total(items, tier="gold", region="east") == 3150
```

### tests/test_pricing_target.py::test_gold_bonus_requires_three_items
```python
def test_gold_bonus_requires_three_items():
    """只有 2 件时 gold 奖励不生效：2000 - 100(会员) + 800(运费) = 2700。"""
    items = make_items(2, unit_price_cents=1000)
    assert _total(items, tier="gold", region="east") == 2700
```

### tests/test_pricing_target.py::test_gold_bonus_requires_gold_tier
```python
def test_gold_bonus_requires_gold_tier():
    """silver 满 3 件没有 500 分奖励：3000 - 90(会员) + 800(运费) = 3710。"""
    items = make_items(3, unit_price_cents=1000)
    assert _total(items, tier="silver", region="east") == 3710
```

### tests/test_pricing_target.py::test_basic_member_no_longer_gets_95_percent_at_three_items
```python
def test_basic_member_no_longer_gets_95_percent_at_three_items():
    """basic + 3 件：3000 不打 95 折，只加运费 800 = 3800。

    v1 基线此处为 2850（3000 - 150 体积折扣），改造后应为 3800。
    """
    items = make_items(3, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 3800
```

### tests/test_pricing_target.py::test_volume_discount_is_gone_for_large_basic_order
```python
def test_volume_discount_is_gone_for_large_basic_order():
    """basic + 6 件（小计 6000）：不再有 5% 体积折扣，且免运费 = 6000。"""
    items = make_items(6, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 6000
```

### tests/test_pricing_target.py::test_five_items_ship_free_east
```python
def test_five_items_ship_free_east():
    """满 5 件免运费：basic + 5 件，east，5000 原价不动。"""
    items = make_items(5, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 5000
```

### tests/test_pricing_target.py::test_five_items_ship_free_west
```python
def test_five_items_ship_free_west():
    """满 5 件免运费（west 同样免）。"""
    items = make_items(5, unit_price_cents=1000)
    assert _total(items, tier="basic", region="west") == 5000
```

### tests/test_pricing_target.py::test_four_items_east_pays_800
```python
def test_four_items_east_pays_800():
    """4 件未满 5：east 收 800 分，4000 + 800 = 4800。"""
    items = make_items(4, unit_price_cents=1000)
    assert _total(items, tier="basic", region="east") == 4800
```

### tests/test_pricing_target.py::test_four_items_west_pays_1200
```python
def test_four_items_west_pays_1200():
    """4 件未满 5：west 收 1200 分，4000 + 1200 = 5200。"""
    items = make_items(4, unit_price_cents=1000)
    assert _total(items, tier="basic", region="west") == 5200
```

### tests/test_pricing_target.py::test_coupon_threshold_is_checked_after_member_discount
```python
def test_coupon_threshold_is_checked_after_member_discount():
    """silver + 3 件（小计 3000）+ 券(200, 门槛 2950)。

    会员折扣后金额 = 2910 < 2950，券不生效：
    3000 - 90 + 800 = 3710。若按小计 3000 判定门槛会错误地得到 3510。
    """
    items = make_items(3, unit_price_cents=1000)
    coupon = make_coupon(amount_cents=200, min_spend_cents=2950)
    assert _total(items, tier="silver", region="east", coupon=coupon) == 3710
```

### tests/test_pricing_target.py::test_coupon_applies_when_threshold_matches_post_discount_amount
```python
def test_coupon_applies_when_threshold_matches_post_discount_amount():
    """silver + 3 件 + 券(200, 门槛 2910)：门槛恰好等于会员折扣后金额，券生效。

    3000 - 90 - 200 + 800 = 3510。
    """
    items = make_items(3, unit_price_cents=1000)
    coupon = make_coupon(amount_cents=200, min_spend_cents=2910)
    assert _total(items, tier="silver", region="east", coupon=coupon) == 3510
```

### tests/test_pricing_target.py::test_gold_three_items_with_coupon_combo
```python
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
```

### tests/test_pricing_target.py::test_gold_three_items_with_coupon_combo_west
```python
def test_gold_three_items_with_coupon_combo_west():
    """同上但 west：运费 1200，顺序不变 → 4700 + 1200 = 5900。"""
    items = make_items(3, unit_price_cents=2000)
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert _total(items, tier="gold", region="west", coupon=coupon) == 5900
```

### tests/test_pricing_target.py::test_gold_bonus_with_fractional_member_discount
```python
def test_gold_bonus_with_fractional_member_discount():
    """999 分订单：会员折扣向下取整 49，再减 500，再加快递 800 = 1250。"""
    items = [make_item(unit_price_cents=333, qty=3)]  # 小计 999
    assert _total(items, tier="gold", region="east") == 1250
```

### tests/test_pricing_target.py::test_total_floor_still_applies_after_shipping
```python
def test_total_floor_still_applies_after_shipping():
    """券把金额扣到 0 后再加运费，总价仍非负且等于运费。

    basic + 1 件 500 + 券(100000, 门槛 0)：max(0, 500-500) + 800 = 800。
    """
    items = [make_item(unit_price_cents=500, qty=1)]
    coupon = make_coupon(amount_cents=100000, min_spend_cents=0)
    assert _total(items, tier="basic", region="east", coupon=coupon) == 800
```

### 回归测试（修改前后都必须全部通过）
### tests/test_pricing_regression.py::test_subtotal_sums_line_totals
```python
def test_subtotal_sums_line_totals():
    """小计 = 各行 单价 × 数量 之和。"""
    items = [
        make_item(unit_price_cents=1999, qty=2),
        make_item(unit_price_cents=500, qty=5),
    ]
    assert subtotal_cents(items) == 1999 * 2 + 500 * 5 == 6498
```

### tests/test_pricing_regression.py::test_subtotal_of_empty_order_is_zero
```python
def test_subtotal_of_empty_order_is_zero():
    """空明细小计为 0。"""
    assert subtotal_cents([]) == 0
```

### tests/test_pricing_regression.py::test_subtotal_of_single_item
```python
def test_subtotal_of_single_item():
    """单行明细的小计。"""
    assert subtotal_cents([make_item(unit_price_cents=1250, qty=3)]) == 3750
```

### tests/test_pricing_regression.py::test_silver_member_gets_three_percent_discount
```python
def test_silver_member_gets_three_percent_discount():
    assert member_discount_cents(10000, "silver") == 300
```

### tests/test_pricing_regression.py::test_gold_member_gets_five_percent_discount
```python
def test_gold_member_gets_five_percent_discount():
    assert member_discount_cents(10000, "gold") == 500
```

### tests/test_pricing_regression.py::test_basic_member_has_no_discount
```python
def test_basic_member_has_no_discount():
    assert member_discount_cents(10000, "basic") == 0
    assert member_discount_cents(1, "basic") == 0
```

### tests/test_pricing_regression.py::test_member_discount_floors_to_whole_cents
```python
def test_member_discount_floors_to_whole_cents():
    """折扣向下取整，且结果始终是 int（不引入浮点分）。"""
    silver = member_discount_cents(999, "silver")  # 29.97 -> 29
    gold = member_discount_cents(999, "gold")  # 49.95 -> 49
    assert silver == 29
    assert gold == 49
    assert isinstance(silver, int) and not isinstance(silver, bool)
    assert isinstance(gold, int) and not isinstance(gold, bool)
```

### tests/test_pricing_regression.py::test_coupon_below_min_spend_yields_nothing
```python
def test_coupon_below_min_spend_yields_nothing():
    """未达门槛：券不打折。"""
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert coupon_discount_cents(4999, coupon) == 0
```

### tests/test_pricing_regression.py::test_coupon_discount_capped_by_amount
```python
def test_coupon_discount_capped_by_amount():
    """券面额大于应付金额时，只扣到 0，不产生负金额。"""
    coupon = make_coupon(amount_cents=1000, min_spend_cents=0)
    assert coupon_discount_cents(300, coupon) == 300
```

### tests/test_pricing_regression.py::test_coupon_at_exact_min_spend_applies
```python
def test_coupon_at_exact_min_spend_applies():
    """金额恰好等于门槛时券生效。"""
    coupon = make_coupon(amount_cents=500, min_spend_cents=5000)
    assert coupon_discount_cents(5000, coupon) == 500
```

### tests/test_pricing_regression.py::test_final_price_of_empty_order_is_zero
```python
def test_final_price_of_empty_order_is_zero():
    """空订单最终价为 0（SPEC-ORD-002 不变量）。"""
    customer = make_customer(tier="gold", region="west")
    assert final_price_cents([], customer) == 0
    assert final_price_cents([], customer, make_coupon(100, 0)) == 0
```

### tests/test_pricing_regression.py::test_final_price_never_goes_negative
```python
def test_final_price_never_goes_negative():
    """券面额远大于订单金额时，总价被夹到 0 而非负数。"""
    customer = make_customer(tier="basic", region="east")
    items = [make_item(unit_price_cents=500, qty=1)]
    coupon = make_coupon(amount_cents=100000, min_spend_cents=0)
    assert final_price_cents(items, customer, coupon) >= 0
```

### tests/test_pricing_regression.py::test_final_price_is_integer_cents
```python
def test_final_price_is_integer_cents():
    """最终价必须是 int（整数分），不是 float / Decimal。"""
    customer = make_customer(tier="silver", region="east")
    items = [make_item(unit_price_cents=1234, qty=1)]
    total = final_price_cents(items, customer, make_coupon(amount_cents=99, min_spend_cents=0))
    assert isinstance(total, int) and not isinstance(total, bool)
```

### tests/test_pricing_regression.py::test_coupon_never_increases_total
```python
def test_coupon_never_increases_total():
    """同一订单加上一张达标券后，总价不会变高。"""
    customer = make_customer(tier="basic", region="east")
    items = [make_item(unit_price_cents=10000, qty=1)]
    coupon = make_coupon(amount_cents=1500, min_spend_cents=5000)
    assert final_price_cents(items, customer, coupon) < final_price_cents(items, customer)
```

### tests/test_pricing_regression.py::test_final_price_does_not_mutate_inputs
```python
def test_final_price_does_not_mutate_inputs():
    """计价是纯函数，不修改入参。"""
    items = [make_item(unit_price_cents=800, qty=2)]
    customer = Customer(customer_id="C-9", tier="gold", region="west")
    final_price_cents(items, customer, make_coupon(50, 0))
    assert items == [Item(name="widget", unit_price_cents=800, qty=2)]
    assert customer == Customer(customer_id="C-9", tier="gold", region="west")
```

## 任务状态（来自 PowerContext）
（空状态：这是本任务第一次运行）

## 输出要求
只输出 unified diff，从 `diff --git` 或 `--- a/` 开始，放在一个 ```diff 代码块里。
不要输出任何其他文字。
````

