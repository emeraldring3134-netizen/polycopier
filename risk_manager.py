from __future__ import annotations

from storage import Storage


class RiskManager:
    def __init__(self, cfg: dict, storage: Storage) -> None:
        self.cfg = cfg
        self.storage = storage

    def current_exposure(self) -> float:
        return sum(float(p.get("amount", 0)) for p in self.storage.get_positions())

    def has_market_conflict(self, market_id: str, side: str) -> bool:
        for p in self.storage.get_positions():
            if p.get("market_id") != market_id:
                continue
            existing_side = p.get("side")
            if existing_side != side:
                return True
        return False

    def is_duplicate_signal(self, wallet: str, market_id: str, side: str) -> bool:
        return self.storage.is_copied(wallet=wallet, market_id=market_id, side=side)

    def is_tracked_market(self, market_id: str, side: str) -> bool:
        return self.storage.is_market_tracked(market_id, side)

    def slippage_ok(self, expected: float, actual: float) -> bool:
        if expected <= 0:
            return False
        drift = abs(actual - expected) / expected
        return drift <= self.cfg["risk"].get("slippage_protection_percent", 0.05)
