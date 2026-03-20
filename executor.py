from __future__ import annotations

import asyncio
import logging
from typing import Any

from polymarket_client import PolymarketClient
from risk_manager import RiskManager
from storage import Storage
from strategy import CopySignal
from utils import now_ts, quantize_amount
from wallet import Wallet


class Executor:
    def __init__(
        self,
        client: PolymarketClient,
        wallet: Wallet,
        risk: RiskManager,
        storage: Storage,
        cfg: dict,
        logger: logging.Logger,
        dry_run: bool,
    ) -> None:
        self.client = client
        self.wallet = wallet
        self.risk = risk
        self.storage = storage
        self.cfg = cfg
        self.logger = logger
        self.dry_run = dry_run

    async def execute_signal(self, s: CopySignal) -> dict[str, Any] | None:
        filters = self.cfg["filters"]
        if not filters.get("allow_conflict", False) and self.risk.has_market_conflict(s.market_id, s.side):
            self.logger.info("risk blocked: market conflict market=%s side=%s", s.market_id, s.side)
            return None

        if filters.get("skip_existing_position", True) and self.risk.is_duplicate_signal(s.wallet, s.market_id, s.side):
            self.logger.info("risk blocked: duplicate signal wallet=%s market=%s", s.wallet, s.market_id)
            return None

        max_retries = self.cfg["risk"].get("max_order_retries", 3)
        payload = f"place:{s.market_id}:{s.side}:{s.amount_usd}:{s.entry_price}:{now_ts()}"
        signature = self.wallet.sign_message(payload)

        for attempt in range(1, max_retries + 1):
            result = await self.client.place_order(
                wallet_address=self.wallet.address,
                signature=signature,
                market_id=s.market_id,
                side=s.side,
                amount_usd=quantize_amount(s.amount_usd),
                price=s.entry_price,
                dry_run=self.dry_run,
            )
            status = str(result.get("status", "")).lower()
            if status in {"simulated", "ok", "filled", "success"} or result.get("order_id"):
                actual_price = float(result.get("filled_price") or s.entry_price)
                if not self.risk.slippage_ok(s.entry_price, actual_price):
                    self.logger.warning(
                        "risk blocked: slippage too high market=%s expected=%.6f actual=%.6f",
                        s.market_id,
                        s.entry_price,
                        actual_price,
                    )
                    return None
                self.storage.save_position(
                    {
                        "market_id": s.market_id,
                        "side": s.side,
                        "entry_price": actual_price,
                        "amount": s.amount_usd,
                        "wallet": s.wallet,
                        "timestamp": now_ts(),
                        "order_id": result.get("order_id"),
                    }
                )
                self.storage.mark_copied(s.wallet, s.market_id, s.side)
                self.logger.info("order success market=%s side=%s amount=%.4f", s.market_id, s.side, s.amount_usd)
                return result

            self.logger.error("order failed attempt=%d market=%s result=%s", attempt, s.market_id, result)
            await asyncio.sleep(min(attempt, 3))
        return None

    async def evaluate_exits(self, smart_wallet_positions: dict[tuple[str, str], bool]) -> None:
        positions = self.storage.get_positions()
        exit_cfg = self.cfg["exit"]
        for p in positions:
            market_id = p["market_id"]
            side = p["side"]
            entry_price = float(p["entry_price"])
            amount = float(p["amount"])
            opened_at = int(p["timestamp"])

            market_map = await self.client.get_market_data_batch([market_id])
            market = market_map.get(market_id)
            if not market:
                continue

            pnl = (market.current_price - entry_price) / entry_price if entry_price > 0 else 0
            if side == "NO":
                pnl = -pnl

            hold_hours = (now_ts() - opened_at) / 3600
            should_exit = False
            if pnl >= exit_cfg["take_profit_percent"]:
                should_exit = True
            if pnl <= exit_cfg["stop_loss_percent"]:
                should_exit = True
            if hold_hours > exit_cfg["max_hold_hours"]:
                should_exit = True
            if exit_cfg.get("follow_smart_wallet_exit", True):
                if smart_wallet_positions.get((market_id, side), True) is False:
                    should_exit = True

            if not should_exit:
                continue

            payload = f"close:{market_id}:{side}:{amount}:{market.current_price}:{now_ts()}"
            signature = self.wallet.sign_message(payload)
            result = await self.client.close_position(
                wallet_address=self.wallet.address,
                signature=signature,
                market_id=market_id,
                side=side,
                amount_usd=amount,
                price=market.current_price,
                dry_run=self.dry_run,
            )
            status = str(result.get("status", "")).lower()
            if status in {"simulated", "ok", "filled", "success"} or result.get("order_id"):
                self.storage.remove_position(market_id, side)
                self.logger.info("exit success market=%s side=%s pnl=%.4f", market_id, side, pnl)
            else:
                self.logger.error("exit failed market=%s side=%s result=%s", market_id, side, result)
