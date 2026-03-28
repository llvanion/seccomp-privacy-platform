from __future__ import annotations

from typing import Any

from app.errors import GatewayError


_ORDER_FIXTURES: dict[str, dict[str, Any]] = {
    "demo-1001": {
        "order_id": "demo-1001",
        "user_name": "Alice Chen",
        "phone": "13800138000",
        "email": "alice.chen@example.com",
        "shipping_address": "Shanghai Pudong New Area Expo Avenue 1000",
        "id_number": "310101199901011234",
        "amount": 199.0,
        "currency": "CNY",
        "note": "demo order for W6 capability token flow",
    },
    "demo-1002": {
        "order_id": "demo-1002",
        "user_name": "Bob Li",
        "phone": "13900139000",
        "email": "bob.li@example.com",
        "shipping_address": "Beijing Haidian Zhongguancun Street 88",
        "id_number": "110101199512123456",
        "amount": 88.5,
        "currency": "CNY",
        "note": "secondary demo order",
    },
}


def get_sensitive_order(order_id: str) -> dict[str, Any]:
    order = _ORDER_FIXTURES.get(order_id)
    if order is None:
        raise GatewayError("order_not_found", f"order not found: {order_id}", status_code=404)
    return dict(order)


def _mask_keep_tail(value: str, prefix: int, suffix: int) -> str:
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    return f"{value[:prefix]}{'*' * (len(value) - prefix - suffix)}{value[-suffix:]}"


def mask_sensitive_order(order: dict[str, Any]) -> dict[str, Any]:
    masked = dict(order)
    masked["phone"] = _mask_keep_tail(str(masked["phone"]), 3, 4)
    email = str(masked["email"])
    local, _, domain = email.partition("@")
    masked["email"] = f"{local[:2]}***@{domain}" if domain else "***"
    masked["shipping_address"] = str(masked["shipping_address"])[:12] + "***"
    masked["id_number"] = _mask_keep_tail(str(masked["id_number"]), 2, 2)
    masked["user_name"] = str(masked["user_name"])[0] + "***"
    return masked
