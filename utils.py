from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any


def now_ts() -> int:
    return int(time.time())


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    return obj


def quantize_amount(value: float, decimals: int = 6) -> float:
    q = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_DOWN))
