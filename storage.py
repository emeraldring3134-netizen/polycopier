from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

from utils import now_ts


class Storage:
    def __init__(self, path: str = "positions.json") -> None:
        self.path = path
        self._lock = Lock()
        if not os.path.exists(self.path):
            self._write({"positions": [], "copied_signals": []})

    def _read(self) -> dict[str, Any]:
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_positions(self) -> list[dict[str, Any]]:
        return self._read().get("positions", [])

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
