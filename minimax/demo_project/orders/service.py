"""订单查询服务。

对外主入口为 :func:`list_orders`，用于按条件筛选订单列表。
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .models import Order


def list_orders(
    orders: Iterable[Order],
    status: Optional[str] = None,
    min_amount: Optional[float] = None,
) -> List[Order]:
    """查询订单列表。

    参数:
        orders: 待筛选的订单集合（函数内部会复制，不会就地修改入参）。
        status: 订单状态筛选条件。**当前实现尚未接入该过滤逻辑**，
            传入后会被忽略（见下方 TODO）。
        min_amount: 最低金额筛选条件，仅返回金额 ``>= min_amount`` 的订单；
            为 ``None`` 时不做金额过滤。

    返回:
        新的订单列表，始终按 ``id`` 升序排列。
    """
    # 复制一份，避免修改调用方传入的集合
    result: List[Order] = list(orders)

    # ---- 已实现：最低金额过滤 ----
    if min_amount is not None:
        result = [order for order in result if order.amount >= min_amount]

    # ---- 未实现：状态过滤 ----
    # TODO: status filter not implemented yet
    if status is not None:
        # 当前忽略 status 参数，直接返回（待实现按状态筛选）
        pass

    # ---- 保持原有行为：按 id 升序排序 ----
    result.sort(key=lambda order: order.id)

    return result