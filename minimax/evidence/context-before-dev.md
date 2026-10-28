# 开发上下文 · TASK-ORD-PRICING-V2

- 标题：订单计价切换到 SPEC-ORD-001 v2 优惠与包邮规则
- 描述：按 SPEC-ORD-001 v2（2026-11-01 生效）改造 ordercore 计价：取消满 3 件 95 折；gold 会员满 3 件额外减 500 分；满 5 件免运费，未满 5 件按区域收运费 east 800 分、west 1200 分；计算顺序为会员折扣→优惠券→gold 奖励→运费；保持金额整数分与总价非负。
- 上下文摘要：`2deac0edeea011728d2f5ea037837e1a7f90a3d308a17020a2414e31e3c9ce9b`
- 生成时间：2026-10-28T08:02:20.117054+00:00

## 适用规格

### SPEC-ORD-001 revision 2 · specs/SPEC-ORD-001.v2.md
- 锚点：`SPEC-ORD-001#r2`
- 选择原因：task 声明规格 SPEC-ORD-001；关键词检索命中

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

### SPEC-ORD-002 revision 1 · specs/SPEC-ORD-002.v1.md
- 锚点：`SPEC-ORD-002#r1`
- 选择原因：task 声明规格 SPEC-ORD-002；关键词检索命中

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

## 需要修改的代码

### src/ordercore/pricing.py::volume_discount_cents  (81-88)
- 选择原因：任务提示符号命中
```python
def volume_discount_cents(amount_cents: int, item_count: int) -> int:
    """体积折扣（分）——**v1 规则**：件数 >= 3 时按 5% 折扣，向下取整。

    SPEC-ORD-001 revision 2 自 2026-11-01 起取消本规则（恒为 0）。
    """
    if item_count >= _VOLUME_DISCOUNT_MIN_ITEMS:
        return _percent_floor(amount_cents, _VOLUME_DISCOUNT_PERCENT)
    return 0
```

### src/ordercore/pricing.py::loyalty_bonus_cents  (91-98)
- 选择原因：任务提示符号命中
```python
def loyalty_bonus_cents(customer: Customer, item_count: int) -> int:
    """忠诚奖励（分）——**v2 待实现**，基线固定返回 0。

    v2 规则（SPEC-ORD-001 rev 2）：``customer.tier == "gold"`` 且
    ``item_count >= 3`` 时，额外减免 500 分；其余情况为 0。
    保留参数与返回类型，使调用方可以在不改签名的情况下替换实现。
    """
    return 0
```

### src/ordercore/pricing.py::shipping_fee_cents  (101-111)
- 选择原因：任务提示符号命中
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

### src/ordercore/pricing.py::final_price_cents  (114-135)
- 选择原因：任务提示符号命中
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

### src/ordercore/pricing.py::_percent_floor  (42-44)
- 选择原因：任务提示文件命中
```python
def _percent_floor(amount_cents: int, percent: int) -> int:
    """按百分比向下取整返回整数分，全程整数运算。"""
    return (amount_cents * percent) // 100
```

### src/ordercore/pricing.py::_item_lines  (47-48)
- 选择原因：任务提示文件命中
```python
def _item_lines(items: Iterable[Item]) -> List[Item]:
    return list(items)
```

### src/ordercore/pricing.py::_item_count  (51-53)
- 选择原因：任务提示文件命中
```python
def _item_count(items: Iterable[Item]) -> int:
    """件数定义：所有明细的 ``qty`` 之和（不是明细行数）。"""
    return sum(item.qty for item in items)
```

### src/ordercore/pricing.py::subtotal_cents  (56-58)
- 选择原因：任务提示文件命中
```python
def subtotal_cents(items: Iterable[Item]) -> int:
    """订单小计（分）：各行 ``unit_price_cents * qty`` 之和。空明细返回 0。"""
    return sum(item.unit_price_cents * item.qty for item in items)
```

### src/ordercore/pricing.py::member_discount_cents  (61-65)
- 选择原因：任务提示文件命中
```python
def member_discount_cents(amount_cents: int, tier: str) -> int:
    """会员折扣（分）：silver 3%、gold 5%、basic 0%，向下取整。"""
    if tier not in _MEMBER_DISCOUNT_PERCENT:
        raise ValueError(f"未知会员等级: {tier!r}")
    return _percent_floor(amount_cents, _MEMBER_DISCOUNT_PERCENT[tier])
```

### src/ordercore/pricing.py::coupon_discount_cents  (68-78)
- 选择原因：任务提示文件命中
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

### src/ordercore/models.py::Item  (17-37)
- 选择原因：任务提示文件命中
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

### src/ordercore/models.py::Customer  (41-52)
- 选择原因：任务提示文件命中
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

### src/ordercore/models.py::Coupon  (56-71)
- 选择原因：任务提示文件命中
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

### 目标测试（改前失败，改后必须通过）
- `tests/test_pricing_target.py::test_gold_member_with_three_items_gets_extra_500_off`
- `tests/test_pricing_target.py::test_gold_bonus_requires_three_items`
- `tests/test_pricing_target.py::test_gold_bonus_requires_gold_tier`
- `tests/test_pricing_target.py::test_basic_member_no_longer_gets_95_percent_at_three_items`
- `tests/test_pricing_target.py::test_volume_discount_is_gone_for_large_basic_order`
- `tests/test_pricing_target.py::test_five_items_ship_free_east`
- `tests/test_pricing_target.py::test_five_items_ship_free_west`
- `tests/test_pricing_target.py::test_four_items_east_pays_800`
- `tests/test_pricing_target.py::test_four_items_west_pays_1200`
- `tests/test_pricing_target.py::test_coupon_threshold_is_checked_after_member_discount`
- `tests/test_pricing_target.py::test_coupon_applies_when_threshold_matches_post_discount_amount`
- `tests/test_pricing_target.py::test_gold_three_items_with_coupon_combo`
- `tests/test_pricing_target.py::test_gold_three_items_with_coupon_combo_west`
- `tests/test_pricing_target.py::test_gold_bonus_with_fractional_member_discount`
- `tests/test_pricing_target.py::test_total_floor_still_applies_after_shipping`

### 回归测试（改前改后都必须通过）
- `tests/test_pricing_regression.py::test_subtotal_sums_line_totals`
- `tests/test_pricing_regression.py::test_subtotal_of_empty_order_is_zero`
- `tests/test_pricing_regression.py::test_subtotal_of_single_item`
- `tests/test_pricing_regression.py::test_silver_member_gets_three_percent_discount`
- `tests/test_pricing_regression.py::test_gold_member_gets_five_percent_discount`
- `tests/test_pricing_regression.py::test_basic_member_has_no_discount`
- `tests/test_pricing_regression.py::test_member_discount_floors_to_whole_cents`
- `tests/test_pricing_regression.py::test_coupon_below_min_spend_yields_nothing`
- `tests/test_pricing_regression.py::test_coupon_discount_capped_by_amount`
- `tests/test_pricing_regression.py::test_coupon_at_exact_min_spend_applies`
- `tests/test_pricing_regression.py::test_final_price_of_empty_order_is_zero`
- `tests/test_pricing_regression.py::test_final_price_never_goes_negative`
- `tests/test_pricing_regression.py::test_final_price_is_integer_cents`
- `tests/test_pricing_regression.py::test_coupon_never_increases_total`
- `tests/test_pricing_regression.py::test_final_price_does_not_mutate_inputs`

## 任务状态（PowerContext）

```json
{}
```

## 数据库查询记录（seekdb）

- rows=0 ·  · `CREATE TABLE IF NOT EXISTS sdd_materials ( mat_id VARCHAR(191) NOT NULL, kind VARCHAR(16) NOT NULL, path VARCHAR(255) NOT NULL, anchor VARCHAR(255) NOT NULL, sy`
- rows=0 ·  · `CREATE TABLE IF NOT EXISTS sdd_import_runs ( run_id VARCHAR(64) NOT NULL, imported_at VARCHAR(32) NOT NULL, spec_count INT NOT NULL, code_count INT NOT NULL, te`
- rows=6 · inspect indexes · `SHOW INDEX FROM sdd_materials`
- rows=0 · spec fulltext search · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=1 · spec fulltext search (relaxed) · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=0 · spec fulltext search · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=1 · spec fulltext search (relaxed) · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=0 · spec fulltext search · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=2 · spec fulltext search (relaxed) · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=4 · get code · `SELECT * FROM sdd_materials WHERE kind = %s AND symbol IN (%s,%s,%s,%s) ORDER BY path, line_start`
- rows=10 · get code · `SELECT * FROM sdd_materials WHERE kind = %s AND path = %s ORDER BY path, line_start`
- rows=3 · get code · `SELECT * FROM sdd_materials WHERE kind = %s AND path = %s ORDER BY path, line_start`
- rows=0 · code fulltext search · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=13 · code fulltext search (relaxed) · `SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, line_start, line_end, digest, MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE`
- rows=15 · get test · `SELECT * FROM sdd_materials WHERE kind = %s AND path = %s ORDER BY path, line_start`
- rows=15 · get test · `SELECT * FROM sdd_materials WHERE kind = %s AND path = %s ORDER BY path, line_start`
