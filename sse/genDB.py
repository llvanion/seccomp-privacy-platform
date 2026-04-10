import json

template = {
    "users": [
        {
            "user_id": "U10001",
            "username": "userName1",
            "email": "user1@example.com",
            "phone": "13800000000",
            "register_time": "2026-01-01T10:00:00Z",
            "level": "VIP1",
            "points": 320,
            "behaviors": {
                "purchase": [{"order_id": "O30001", "time": "2026-02-01T12:30:00Z"}],
                "view": [
                    {
                        "product_id": "P20001",
                        "time": "2026-02-01T11:00:00Z",
                        "duration_seconds": 45,
                    }
                ],
                "likes": [{"product_id": "P20001", "time": "2026-02-01T11:05:00Z"}],
                "cart": [
                    {
                        "product_id": "P20001",
                        "quantity": 1,
                        "time": "2026-02-01T11:10:00Z",
                    }
                ],
            },
        }
    ],
    "products": [
        {
            "product_id": "P20001",
            "name": "Wireless Mouse",
            "category": "Electronics",
            "price": 99.00,
            "stock": 120,
            "brand": "LogiTech",
            "created_at": "2025-12-20T08:00:00Z",
        }
    ],
    "orders": [
        {
            "order_id": "O30001",
            "user_id": "U10001",
            "total_amount": 198.00,
            "status": "delivered",
            "payment_method": "Alipay",
            "created_at": "2026-02-01T12:30:00Z",
            "items": [{"product_id": "P20001", "quantity": 2, "unit_price": 99.00}],
        }
    ],
    "reviews": [
        {
            "review_id": "R40001",
            "user_id": "U10001",
            "product_id": "P20001",
            "rating": 5,
            "content": "Very good quality!",
            "created_at": "2026-02-03T09:00:00Z",
        }
    ],
}


json.dump(template, open("db.json", "w"), indent=4)