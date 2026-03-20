from __future__ import annotations

from dataclasses import dataclass

from polymarket_client import MarketData, SmartWalletPosition
from utils import clamp


@dataclass
class CopySignal:
    wallet: str
    market_id: str
    side: str
    amount_usd: float
    entry_price: float
    conviction_score: float
    smart_position: SmartWalletPosition


class Strategy:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def conviction_score(self, p: SmartWalletPosition) -> float:
        position_ratio = 0.0
        if p.wallet_total_usd > 0:
            position_ratio = clamp(p.position_size_usd / p.wallet_total_usd, 0.0, 1.0)

        hold_hours = clamp((self._now() - p.opened_at_ts) / 3600 if p.opened_at_ts else 0.0, 0.0, 72.0)
        hold_ratio = hold_hours / 72.0
        add_ratio = clamp(p.add_position_count, 0, 3) / 3.0
        return 0.5 * position_ratio + 0.2 * hold_ratio + 0.3 * add_ratio

    def build_signals(
        self,
        positions: list[SmartWalletPosition],
        market_map: dict[str, MarketData],
        current_total_exposure: float,
    ) -> list[CopySignal]:
        filters = self.cfg["filters"]
        pos_cfg = self.cfg["position"]
        out: list[CopySignal] = []

        for p in positions:
            m = market_map.get(p.market_id)
            if not m:
                continue
            if p.position_size_usd < filters["min_position_size_usd"]:
                continue
            score = self.conviction_score(p)
            if score < filters["min_conviction_score"]:
                continue
            if m.current_price <= 0 or p.entry_price <= 0:
                continue
            drift = abs(m.current_price - p.entry_price) / p.entry_price
            if drift > filters["max_price_drift"]:
                continue
            if m.expiry_ts > 0:
                minutes_left = (m.expiry_ts - self._now()) / 60
                if minutes_left < filters["min_time_to_expiry_minutes"]:
                    continue

            amount = min(
                p.position_size_usd * pos_cfg["copy_ratio"],
                pos_cfg["max_single_position_usd"],
            )
            if current_total_exposure + amount > pos_cfg["max_total_exposure_usd"]:
                continue

            out.append(
                CopySignal(
                    wallet=p.wallet,
                    market_id=p.market_id,
                    side=p.side,
                    amount_usd=amount,
                    entry_price=m.current_price,
                    conviction_score=score,
                    smart_position=p,
                )
            )
        return out

    @staticmethod
    def _now() -> int:
        import time

        return int(time.time())
