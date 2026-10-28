"""订单数据模型。

本模块仅定义领域对象（不含业务规则），便于被服务层与测试复用。
"""

from __future__ import annotations

from dataclasses import dataclass

# 订单允许的状态取值（业务约束）
#   paid      —— 已支付
#   pending   —— 待支付
#   cancelled —— 已取消
VALID_STATUSES = ("paid", "pending", "cancelled")


@dataclass
class Order:
    """一笔订单。

    Attributes:
        id: 订单唯一编号（整数，用于稳定排序）。
        customer: 客户名称。
        amount: 订单金额（元）。
        status: 订单状态，取值见 :data:`VALID_STATUSES`。
    """

    id: int
    customer: str
    amount: float
    status: str

    def __post_init__(self) -> None:
        """构造时校验状态合法性，避免脏数据流入业务逻辑。"""
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"非法订单状态: {self.status!r}，合法取值: {VALID_STATUSES}"
            )