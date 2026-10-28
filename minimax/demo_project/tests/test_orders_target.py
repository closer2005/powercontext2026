"""目标测试：验证 list_orders 的「状态筛选」能力。

这些用例描述的是**待实现的目标行为**：

- 在 ``status`` 过滤尚未实现时，本文件必须 **FAIL**（且失败原因必须是断言失败，
  而不是导入错误等环境问题）；
- 在 ``service.list_orders`` 补上 status 过滤后，本文件必须 **PASS**。
"""

from orders.models import Order
from orders.service import list_orders


def _make_orders() -> list[Order]:
    """构造自包含的测试数据（不依赖任何外部文件）。"""
    return [
        Order(id=1, customer="张三", amount=100.0, status="paid"),
        Order(id=2, customer="李四", amount=50.0, status="pending"),
        Order(id=3, customer="王五", amount=200.0, status="paid"),
        Order(id=4, customer="赵六", amount=75.0, status="cancelled"),
    ]


def test_filter_by_status():
    """仅传入 status="paid" 时，应只返回已支付订单。"""
    orders = _make_orders()

    result = list_orders(orders, status="paid")

    # 只应包含 paid 订单（id=1、id=3），且保持 id 升序
    assert [order.id for order in result] == [1, 3]
    assert all(order.status == "paid" for order in result)