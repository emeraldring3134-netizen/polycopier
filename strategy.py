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
    score: float
    smart_position: SmartWalletPosition


class Strategy:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def score_position(self, p: SmartWalletPosition) -> float:
        position_ratio = 0.0
        if p.wallet_total_usd > 0:
            position_ratio = clamp(p.position_size_usd / p.wallet_total_usd, 0.0, 1.0)
        hold_hours = clamp((self._now() - p.opened_at_ts) / 3600 if p.opened_at_ts else 0.0, 0.0, 72.0)
        hold_ratio = hold_hours / 72.0
        add_ratio = clamp(p.add_position_count, 0, 3) / 3.0
        # 综合评分：规模+持仓时间+加仓行为
        return 0.5 * position_ratio + 0.2 * hold_ratio + 0.3 * add_ratio

    def _mode(self, exposure: float) -> tuple[int, int | None]:
        # (top_n override, max_new_orders)
        if exposure < 2:
            return 10, None
        if exposure <= 5:
            return 8, None
        return 3, 1

    def build_signals(
        self,
        positions: list[SmartWalletPosition],
        market_map: dict[str, MarketData],
        current_total_exposure: float,
    ) -> list[CopySignal]:
        filters = self.cfg["filters"]
        pos_cfg = self.cfg["position"]
        mode_top_n, max_new_orders = self._mode(current_total_exposure)
        top_n = int(self.cfg["strategy"].get("top_n_wallet_positions", 8))
        top_n = min(top_n, mode_top_n)

        candidates: list[CopySignal] = []
        for p in positions:
            m = market_map.get(p.market_id)
            if not m:
                continue
            if p.position_size_usd < filters["min_position_size_usd"]:
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

            candidates.append(
                CopySignal(
                    wallet=p.wallet,
                    market_id=p.market_id,
                    side=p.side,
                    amount_usd=amount,
                    entry_price=m.current_price,
                    score=self.score_position(p),
                    smart_position=p,
                )
            )

        candidates.sort(key=lambda x: x.score, reverse=True)
        selected = candidates[:top_n]
        if max_new_orders is not None:
            selected = selected[:max_new_orders]
        return selected

    @staticmethod
    def _now() -> int:
        import time

        return int(time.time())
