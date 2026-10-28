"""回归测试：锁定 list_orders 的「原有行为」。

语义为「原有行为必须保持」：无论后续如何修改 ``service.py``，
本文件的三个用例在**修改前后都必须 PASS**。

说明：本文件刻意不涉及尚未实现的 status 过滤，因此其结论不会随目标功能
的实现而变化，可作为回归基线。
"""

from orders.models import Order
from orders.service import list_orders


def _make_orders() -> list[Order]:
    """构造自包含的测试数据（不依赖任何外部文件），并故意打乱 id 顺序。"""
    return [
        Order(id=3, customer="王五", amount=200.0, status="paid"),
        Order(id=1, customer="张三", amount=100.0, status="paid"),
        Order(id=4, customer="赵六", amount=75.0, status="cancelled"),
        Order(id=2, customer="李四", amount=50.0, status="pending"),
    ]


def test_list_orders_returns_all():
    """不传任何筛选参数时，应返回全部订单。"""
    orders = _make_orders()

    result = list_orders(orders)

    # 数量一致，且 id 集合完全覆盖
    assert len(result) == len(orders)
    assert {order.id for order in result} == {1, 2, 3, 4}


def test_filter_by_min_amount():
    """按最低金额过滤：仅返回金额 >= min_amount 的订单。"""
    orders = _make_orders()

    result = list_orders(orders, min_amount=100.0)

    # 金额 >= 100 的只有 id=1(100.0) 与 id=3(200.0)
    assert [order.id for order in result] == [1, 3]
    assert all(order.amount >= 100.0 for order in result)


def test_sorted_by_id():
    """结果必须按 id 升序排列。"""
    orders = _make_orders()

    result = list_orders(orders)

    ids = [order.id for order in result]
    assert ids == sorted(ids)