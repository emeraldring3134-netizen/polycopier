from __future__ import annotations

import asyncio
import logging
from typing import Any

from notifier import FeishuNotifier
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
        proxy_wallet: str | None,
        notifier: FeishuNotifier,
    ) -> None:
        self.client = client
        self.wallet = wallet
        self.risk = risk
        self.storage = storage
        self.cfg = cfg
        self.logger = logger
        self.dry_run = dry_run
        self.proxy_wallet = proxy_wallet
        self.notifier = notifier

    async def sync_positions_from_trades(self, iteration: int) -> None:
        # 从 funder 的真实成交重建当前持仓，避免本地状态漂移。
        positions = await self.client.get_funder_open_positions(self.wallet.address)
        rebuilt: list[dict[str, Any]] = []
        for item in positions:
            rebuilt.append(
                {
                    "market_id": item["market_id"],
                    "side": item["side"],
                    "entry_price": item["entry_price"],
                    "amount": item["shares"] * item["entry_price"],
                    "shares": item["shares"],
                    "timestamp": now_ts(),
                    "max_pnl_percent": 0.0,
                }
            )
        self.storage.replace_positions(rebuilt)
        self.logger.info("positions synced from funder trades count=%d", len(rebuilt), extra={"iteration": iteration})

    async def check_pending_orders(self, iteration: int) -> None:
        pending = self.storage.get_pending_orders()
        if not pending:
            return
        orders = await self.client.get_orders(self.wallet.address)
        order_map = {str(o.get("id") or o.get("order_id")): o for o in orders}
        timeout_sec = int(self.cfg["risk"].get("pending_timeout_minutes", 30)) * 60

        keep: list[dict[str, Any]] = []
        for p in pending:
            oid = str(p.get("order_id"))
            status = str(order_map.get(oid, {}).get("status", "unknown")).lower()
            if status in {"filled", "done", "success", "canceled", "cancelled"}:
                continue
            if now_ts() - int(p.get("submit_time", now_ts())) > timeout_sec and not p.get("retried"):
                await self.client.cancel_order(oid)
                p["retried"] = True
                p["submit_time"] = now_ts()
                keep.append(p)
                self.logger.warning("pending order timeout and retried order=%s", oid, extra={"iteration": iteration})
                continue
            keep.append(p)
        self.storage.replace_pending_orders(keep)

    async def execute_signal(self, s: CopySignal, iteration: int) -> dict[str, Any] | None:
        filters = self.cfg["filters"]
        if self.risk.has_existing_position(s.market_id):
            self.logger.info("skip existing funder position market=%s", s.market_id, extra={"iteration": iteration})
            return None
        if not filters.get("allow_conflict", False) and self.risk.has_market_conflict(s.market_id, s.side):
            self.logger.info("risk blocked: market conflict market=%s side=%s", s.market_id, s.side, extra={"iteration": iteration})
            return None
        if self.risk.is_tracked_market(s.market_id, s.side):
            self.logger.info("risk blocked: tracked market market=%s side=%s", s.market_id, s.side, extra={"iteration": iteration})
            return None
        if filters.get("skip_existing_position", True) and self.risk.is_duplicate_signal(s.wallet, s.market_id, s.side):
            self.logger.info("risk blocked: duplicate signal wallet=%s market=%s", s.wallet, s.market_id, extra={"iteration": iteration})
            return None

        available = await self.client.get_balance_allowance(self.wallet.address)
        reserve = float(self.cfg["position"].get("reserve_balance_usd", 1))
        budget = max(0.0, available - reserve)
        amount = min(s.amount_usd, budget)
        if amount <= 0:
            self.logger.warning("risk blocked: no budget available=%.4f", available, extra={"iteration": iteration})
            return None

        shares = amount / s.entry_price if s.entry_price > 0 else 0
        if shares < self.cfg["position"].get("min_order_shares", 5):
            self.logger.info("risk blocked: below min shares=%.3f", shares, extra={"iteration": iteration})
            return None

        max_retries = self.cfg["risk"].get("max_order_retries", 3)
        payload = f"place:{s.market_id}:{s.side}:{amount}:{s.entry_price}:{now_ts()}"
        signature = self.wallet.sign_message(payload)

        for attempt in range(1, max_retries + 1):
            result = await self.client.place_order(
                wallet_address=self.wallet.address,
                signature=signature,
                market_id=s.market_id,
                side=s.side,
                amount_usd=quantize_amount(amount),
                price=s.entry_price,
                proxy_wallet=self.proxy_wallet,
                dry_run=self.dry_run,
            )
            status = str(result.get("status", "")).lower()
            if status in {"simulated", "ok", "filled", "success", "pending"} or result.get("order_id"):
                actual_price = float(result.get("filled_price") or s.entry_price)
                if not self.risk.slippage_ok(s.entry_price, actual_price):
                    self.logger.warning(
                        "risk blocked: slippage too high market=%s expected=%.6f actual=%.6f",
                        s.market_id,
                        s.entry_price,
                        actual_price,
                        extra={"iteration": iteration},
                    )
                    return None
                self.storage.save_position(
                    {
                        "market_id": s.market_id,
                        "side": s.side,
                        "entry_price": actual_price,
                        "amount": amount,
                        "shares": shares,
                        "wallet": s.wallet,
                        "timestamp": now_ts(),
                        "order_id": result.get("order_id"),
                        "max_pnl_percent": 0.0,
                    }
                )
                if status == "pending":
                    self.storage.add_pending_order(
                        {
                            "order_id": result.get("order_id"),
                            "market_id": s.market_id,
                            "side": s.side,
                            "submit_time": now_ts(),
                            "retried": False,
                        }
                    )
                self.storage.mark_copied(s.wallet, s.market_id, s.side)
                self.storage.track_market(s.market_id, s.side)
                self.logger.info("order success market=%s side=%s amount=%.4f", s.market_id, s.side, amount, extra={"iteration": iteration})
                return result

            self.logger.error("order failed attempt=%d market=%s result=%s", attempt, s.market_id, result, extra={"iteration": iteration})
            await asyncio.sleep(min(attempt, 3))
        return None

    async def evaluate_exits(self, smart_wallet_positions: dict[tuple[str, str], bool], market_names: dict[str, str], iteration: int) -> None:
        positions = self.storage.get_positions()
        exit_cfg = self.cfg["exit"]
        changed_positions: list[dict[str, Any]] = []
        for p in positions:
            market_id = p["market_id"]
            token_id = str(p.get("token_id") or "")
            side = p["side"]
            entry_price = float(p["entry_price"])
            amount = float(p["amount"])
            shares = float(p.get("shares") or (amount / entry_price if entry_price > 0 else 0))
            opened_at = int(p["timestamp"])

            current = 0.0
            if token_id:
                current = await self.client.get_last_trade_price(token_id)
            if current <= 0:
                market_map = await self.client.get_market_data_batch([market_id])
                market = market_map.get(market_id)
                if not market:
                    changed_positions.append(p)
                    continue
                current = market.current_price

            pnl_percent = ((current - entry_price) / entry_price) if entry_price > 0 else 0
            if side == "NO":
                pnl_percent = -pnl_percent
            p["current_price"] = current
            p["pnl"] = shares * (current - entry_price)
            p["pnl_percent"] = pnl_percent
            p["max_pnl_percent"] = max(float(p.get("max_pnl_percent", 0.0)), pnl_percent)

            if abs(pnl_percent) >= exit_cfg.get("alert_move_percent", 0.15):
                msg = (
                    f"⚠️ 预警：{market_names.get(market_id, market_id)} {side} {shares:.2f}股 "
                    f"{entry_price:.4f} → {current:.4f} ({pnl_percent * 100:.2f}%)"
                )
                await self.notifier.send_text(msg)

            hold_hours = (now_ts() - opened_at) / 3600
            trailing_trigger = (
                p["max_pnl_percent"] >= exit_cfg.get("trailing_activation_profit_percent", 0.3)
                and pnl_percent <= p["max_pnl_percent"] - exit_cfg.get("trailing_drawdown_percent", 0.1)
            )
            stop_loss = pnl_percent <= exit_cfg["stop_loss_percent"]
            timed_out = hold_hours > exit_cfg["max_hold_hours"]
            follow_exit = exit_cfg.get("follow_smart_wallet_exit", True) and smart_wallet_positions.get((market_id, side), True) is False
            should_exit = trailing_trigger or stop_loss or timed_out or follow_exit

            if not should_exit:
                changed_positions.append(p)
                continue

            payload = f"close:{market_id}:{side}:{amount}:{current}:{now_ts()}"
            signature = self.wallet.sign_message(payload)
            closed = False
            for _ in range(self.cfg["risk"].get("max_order_retries", 3)):
                result = await self.client.close_position(
                    wallet_address=self.wallet.address,
                    signature=signature,
                    market_id=market_id,
                    side=side,
                    amount_usd=amount,
                    price=current,
                    proxy_wallet=self.proxy_wallet,
                    dry_run=self.dry_run,
                )
                status = str(result.get("status", "")).lower()
                if status in {"simulated", "ok", "filled", "success"} or result.get("order_id"):
                    self.logger.info("exit success market=%s side=%s pnl=%.4f", market_id, side, pnl_percent, extra={"iteration": iteration})
                    closed = True
                    break
                await asyncio.sleep(1)
            if not closed:
                changed_positions.append(p)
                self.logger.error("exit failed market=%s side=%s", market_id, side, extra={"iteration": iteration})

        self.storage.replace_positions(changed_positions)
