"""pytest 共享配置。

本工程不要求 ``pip install``：这里直接把 ``src`` 目录加入 ``sys.path``，
测试与运行都基于仓库内的源码。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ordercore.models import Coupon, Customer, Item  # noqa: E402  （必须在 sys.path 注入之后导入）

#: 供测试直接使用的便捷构造器 -------------------------------------------------


def make_item(name: str = "widget", unit_price_cents: int = 1000, qty: int = 1) -> Item:
    """构造一条明细。"""
    return Item(name=name, unit_price_cents=unit_price_cents, qty=qty)


def make_items(count: int, unit_price_cents: int = 1000, name: str = "widget") -> list[Item]:
    """构造 ``count`` 件同名同价明细（每行 qty=1）。"""
    return [make_item(name=name, unit_price_cents=unit_price_cents, qty=1) for _ in range(count)]


def make_customer(tier: str = "basic", region: str = "east", customer_id: str = "C-0001") -> Customer:
    """构造客户。"""
    return Customer(customer_id=customer_id, tier=tier, region=region)


def make_coupon(amount_cents: int = 100, min_spend_cents: int = 0, code: str = "SAVE") -> Coupon:
    """构造优惠券。"""
    return Coupon(code=code, amount_cents=amount_cents, min_spend_cents=min_spend_cents)


@pytest.fixture
def item_factory():
    """fixture 形式的明细构造器。"""
    return make_item


@pytest.fixture
def items_factory():
    """fixture 形式的批量明细构造器。"""
    return make_items


@pytest.fixture
def customer_factory():
    """fixture 形式的客户构造器。"""
    return make_customer


@pytest.fixture
def coupon_factory():
    """fixture 形式的优惠券构造器。"""
    return make_coupon


@pytest.fixture
def basic_customer() -> Customer:
    return make_customer(tier="basic", region="east")


@pytest.fixture
def silver_customer() -> Customer:
    return make_customer(tier="silver", region="east")


@pytest.fixture
def gold_customer() -> Customer:
    return make_customer(tier="gold", region="east")