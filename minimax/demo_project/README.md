# demo_project —— 订单业务工程（SDD 改造演示对象）

本目录是 MiniMax 赛题作品的「可运行业务工程」，用于演示 SDD（规格驱动开发）
上下文管理系统的完整闭环：**有规格 → 有代码 → 有测试 → 由 MiniMax 生成改动 →
改动后目标测试转绿、回归测试保持全绿**。

## 目录结构

```
demo_project/
├── README.md                       # 本文件
├── orders/
│   ├── __init__.py                 # 包导出：Order / VALID_STATUSES / list_orders
│   ├── models.py                   # Order 数据类（id/customer/amount/status）
│   └── service.py                  # list_orders(orders, status=None, min_amount=None)
└── tests/
    ├── conftest.py                 # 保证 orders 可从任意目录被导入
    ├── test_orders_baseline.py     # 回归测试：修改前后都必须 PASS
    └── test_orders_target.py       # 目标测试：修改前 FAIL、修改后 PASS
```

## 领域模型

`Order` 为一笔订单，字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `int` | 订单编号，用于结果稳定排序（升序） |
| `customer` | `str` | 客户名称 |
| `amount` | `float` | 订单金额（元） |
| `status` | `str` | 订单状态，取值 `"paid"` / `"pending"` / `"cancelled"` |

状态合法性在 `Order.__post_init__` 中校验，非法值会抛出 `ValueError`。

## 服务接口

```python
list_orders(orders, status=None, min_amount=None) -> list[Order]
```

- `orders`：待筛选的订单集合（内部会复制，不会就地修改入参）。
- `min_amount`：最低金额过滤，**已实现**，仅返回 `amount >= min_amount` 的订单。
- `status`：状态过滤，**当前尚未实现**（`service.py` 中为
  `# TODO: status filter not implemented yet`，传入后被忽略）。
- 无论是否过滤，结果**始终按 `id` 升序**排列。

## 如何运行测试

推荐在 `demo_project` 目录下运行：

```bash
cd minimax/demo_project
python -m pytest tests -q
```

也可以直接在仓库根目录运行（`tests/conftest.py` 已处理导入路径）：

```bash
python -m pytest minimax/demo_project/tests -q
```

## 当前预期结果（改动前）

| 测试文件 | 用例 | 预期 |
|---|---|---|
| `test_orders_baseline.py` | `test_list_orders_returns_all` | **PASS** |
| `test_orders_baseline.py` | `test_filter_by_min_amount` | **PASS** |
| `test_orders_baseline.py` | `test_sorted_by_id` | **PASS** |
| `test_orders_target.py` | `test_filter_by_status` | **FAIL**（status 未实现） |

即：**baseline 3 个全 PASS，target 1 个 FAIL**。

## 修复目标

在 `orders/service.py` 中为 `status` 补上过滤逻辑，使目标测试 `test_filter_by_status`
由 FAIL 变为 PASS，同时三个回归测试保持 PASS。修改仅限该文件、仅限 `status` 分支，
不得修改测试或断言。

## 依赖说明

仅依赖标准库与 `pytest`（测试框架），不需要任何第三方运行时依赖。