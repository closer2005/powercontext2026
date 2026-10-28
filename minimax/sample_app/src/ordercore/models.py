"""ordercore 领域模型。

所有金额一律使用「整数分」（int），禁止浮点参与金额计算。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Item", "Customer", "Coupon", "CUSTOMER_TIERS", "REGIONS"]

CUSTOMER_TIERS = ("basic", "silver", "gold")
REGIONS = ("east", "west")


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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