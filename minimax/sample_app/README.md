# ordercore · 订单计价服务（SDD 示例基线）

一个只有标准库依赖的 Python 订单计价服务，用来演示「规格驱动开发（SDD）」
的最小闭环：**规格 → 目标测试（红）→ 改造 → 目标测试（绿）+ 回归测试（始终绿）**。

* 当前基线 = **SPEC-ORD-001 revision 1**（v1）：会员折扣 + 满 3 件 95 折 + 优惠券。
* `specs/SPEC-ORD-001.v2.md` = **revision 2**（2026-11-01 生效）：
  取消满 3 件 95 折；gold 满 3 件额外减 500 分；满 5 件免运费，否则 east 800 / west 1200；
  顺序为会员折扣 → 优惠券 → gold 奖励 → 运费。
* 因此**基线状态下 `tests/test_pricing_target.py` 是红的（AssertionError）**，
  这是预期行为，不是环境问题；改造完成后它必须全绿，并且 `test_pricing_regression.py` 全程保持全绿。

## 目录

```
.
├── pyproject.toml                       # 项目元数据与 pytest 配置（无运行时依赖）
├── README.md
├── specs
│   ├── SPEC-ORD-001.v1.md               # 计价规则 rev 1（现行基线）
│   ├── SPEC-ORD-001.v2.md               # 计价规则 rev 2（待实现）
│   └── SPEC-ORD-002.v1.md               # 计价不变量（整数分 / 非负 / 券不超额 / 空单为 0）
├── src/ordercore
│   ├── __init__.py
│   ├── models.py                        # Item / Customer / Coupon（dataclass，金额为整数分）
│   └── pricing.py                       # 计价规则与 final_price_cents 计算链路
├── task.yaml                            # 改造任务描述（specs / target_tests / regression_tests / hints）
└── tests
    ├── conftest.py                      # 把 src 加入 sys.path + 构造 helper 与 fixture
    ├── test_pricing_regression.py       # 回归：改造前后都必须通过
    └── test_pricing_target.py           # 目标：基线失败、改造后通过
```

## 运行测试

无需安装本项目，`conftest.py` 会把 `src` 加入 `sys.path`：

```bash
python -m pytest tests -q
```

分开跑：

```bash
python -m pytest tests/test_pricing_regression.py -q   # 基线就应全绿
python -m pytest tests/test_pricing_target.py -q       # 基线红，改造后绿
```

快速 sanity 检查：

```bash
python -c "import sys; sys.path.insert(0,'src'); from ordercore.models import Item, Customer; from ordercore.pricing import final_price_cents; print(final_price_cents([Item('w', 1000, 3)], Customer('C1','gold','east')))"
```

## 计价链路（`final_price_cents`）

```
小计 → 减会员折扣 → 减体积折扣(v1) → 减优惠券 → 加运费 → 下限 0
```

改造 v2 时按规格把它变成：

```
小计 → 减会员折扣 → 减优惠券 → 减 gold 奖励 → 加运费 → 下限 0
```

`volume_discount_cents` / `loyalty_bonus_cents` / `shipping_fee_cents` 是三个可替换的接缝，
`final_price_cents` 每一步都调用独立函数，因此无需重写整段逻辑。

## 约定

* 所有金额为整数分（`int`），百分比折扣向下取整，不出现浮点。
* 「件数」= 各明细 `qty` 之和，不是明细行数。
* 优惠券门槛按调用时刻的当前应付金额判定，所以计算顺序有语义。