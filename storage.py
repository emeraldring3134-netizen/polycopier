from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

from utils import now_ts


class Storage:
    def __init__(self, path: str = "positions.json", tracked_path: str = "tracked-markets.json") -> None:
        self.path = path
        self.tracked_path = tracked_path
        self._lock = Lock()
        if not os.path.exists(self.path):
            self._write(
                {
                    "positions": [],
                    "copied_signals": [],
                    "pending_orders": [],
                }
            )
        if not os.path.exists(self.tracked_path):
            with open(self.tracked_path, "w", encoding="utf-8") as f:
                json.dump({"tracked_markets": []}, f, ensure_ascii=False, indent=2)

    def _read(self) -> dict[str, Any]:
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def _read_tracked(self) -> dict[str, Any]:
        with self._lock:
            with open(self.tracked_path, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write_tracked(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with open(self.tracked_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_positions(self) -> list[dict[str, Any]]:
        return self._read().get("positions", [])

    def replace_positions(self, positions: list[dict[str, Any]]) -> None:
        db = self._read()
        db["positions"] = positions
        self._write(db)

    def save_position(self, position: dict[str, Any]) -> None:
        db = self._read()
        db.setdefault("positions", []).append(position)
        self._write(db)

    def remove_position(self, market_id: str, side: str) -> None:
        db = self._read()
        db["positions"] = [
            p
            for p in db.get("positions", [])
            if not (p.get("market_id") == market_id and p.get("side") == side)
        ]
        self._write(db)

    def mark_copied(self, wallet: str, market_id: str, side: str) -> None:
        db = self._read()
        db.setdefault("copied_signals", []).append(
            {
                "wallet": wallet,
                "market_id": market_id,
                "side": side,
                "timestamp": now_ts(),
            }
        )
        self._write(db)

    def is_copied(self, wallet: str, market_id: str, side: str) -> bool:
        db = self._read()
        for item in db.get("copied_signals", []):
            if (
                item.get("wallet") == wallet
                and item.get("market_id") == market_id
                and item.get("side") == side
            ):
                return True
        return False

    def track_market(self, market_id: str, side: str) -> None:
        db = self._read_tracked()
        key = f"{market_id}:{side}"
        tracked = set(db.get("tracked_markets", []))
        tracked.add(key)
        db["tracked_markets"] = sorted(tracked)
        self._write_tracked(db)

    def is_market_tracked(self, market_id: str, side: str) -> bool:
        db = self._read_tracked()
        return f"{market_id}:{side}" in set(db.get("tracked_markets", []))

    def add_pending_order(self, order: dict[str, Any]) -> None:
        db = self._read()
        db.setdefault("pending_orders", []).append(order)
        self._write(db)

    def get_pending_orders(self) -> list[dict[str, Any]]:
        return self._read().get("pending_orders", [])

    def replace_pending_orders(self, orders: list[dict[str, Any]]) -> None:
        db = self._read()
        db["pending_orders"] = orders
        self._write(db)
