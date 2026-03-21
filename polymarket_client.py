from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass
class SmartWalletPosition:
    wallet: str
    market_id: str
    outcome: str
    side: str
    position_size_usd: float
    wallet_total_usd: float
    entry_price: float
    current_price: float
    opened_at_ts: int
    add_position_count: int
    smart_wallet_closed: bool = False


@dataclass
class MarketData:
    market_id: str
    market_name: str
    current_price: float
    liquidity: float
    expiry_ts: int


class PolymarketClient:
    def __init__(self, rpc_url: str, timeout_seconds: int = 20) -> None:
        self.rpc_url = rpc_url
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.clob_url = "https://clob.polymarket.com"
        self.data_url = "https://gamma-api.polymarket.com"
        self.stats_url = "https://data-api.polymarket.com"

    async def _get_json(self, session: aiohttp.ClientSession, url: str, params: dict[str, Any] | None = None) -> Any:
        for _ in range(3):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status >= 400:
                        await asyncio.sleep(1)
                        continue
                    return await resp.json()
            except aiohttp.ClientError:
                await asyncio.sleep(1)
        return None

    async def get_wallet_positions(self, wallet: str) -> list[SmartWalletPosition]:
        url = f"{self.data_url}/positions"
        params = {"user": wallet, "limit": 100}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            payload = await self._get_json(session, url, params=params)
        if not payload:
            return []

        rows = payload if isinstance(payload, list) else payload.get("data", [])
        positions: list[SmartWalletPosition] = []
        for row in rows:
            try:
                size = float(row.get("size", 0) or row.get("positionSize", 0) or 0)
                if size <= 0:
                    continue
                positions.append(
                    SmartWalletPosition(
                        wallet=wallet,
                        market_id=str(row.get("market") or row.get("market_id") or row.get("conditionId")),
                        outcome=str(row.get("outcome") or row.get("token") or "UNKNOWN"),
                        side=str(row.get("side") or ("YES" if row.get("outcomeIndex") == 0 else "NO")).upper(),
                        position_size_usd=size,
                        wallet_total_usd=float(row.get("walletTotalUsd") or row.get("portfolioValue") or size),
                        entry_price=float(row.get("avgPrice") or row.get("entry_price") or row.get("price") or 0),
                        current_price=float(row.get("currentPrice") or row.get("markPrice") or row.get("price") or 0),
                        opened_at_ts=int(row.get("openedAt") or row.get("createdAt") or row.get("timestamp") or 0),
                        add_position_count=int(row.get("addCount") or row.get("fills") or 1),
                        smart_wallet_closed=bool(row.get("closed") or False),
                    )
                )
            except (ValueError, TypeError):
                continue
        return positions

    async def get_wallet_win_rate_60d(self, wallet: str) -> float:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            payload = await self._get_json(session, f"{self.stats_url}/positions", params={"user": wallet})
        rows = payload if isinstance(payload, list) else payload.get("data", []) if payload else []
        wins = 0
        total = 0
        for row in rows:
            closed_ts = int(row.get("closedAt") or row.get("closed_at") or 0)
            if not closed_ts:
                continue
            import time
            if closed_ts < (int(time.time()) - 60 * 24 * 3600):
                continue
            pnl = float(row.get("realizedPnl") or row.get("pnl") or 0)
            total += 1
            if pnl > 0:
                wins += 1
        return wins / total if total else 0.0

    async def get_market_data_batch(self, market_ids: list[str]) -> dict[str, MarketData]:
        if not market_ids:
            return {}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self._get_json(session, f"{self.data_url}/markets/{market_id}") for market_id in market_ids]
            payloads = await asyncio.gather(*tasks, return_exceptions=True)

        out: dict[str, MarketData] = {}
        for market_id, payload in zip(market_ids, payloads):
            if isinstance(payload, Exception) or not payload:
                continue
            data = payload.get("market", payload) if isinstance(payload, dict) else {}
            try:
                out[market_id] = MarketData(
                    market_id=market_id,
                    market_name=str(data.get("question") or data.get("title") or market_id),
                    current_price=float(data.get("lastTradePrice") or data.get("price") or 0),
                    liquidity=float(data.get("liquidity") or 0),
                    expiry_ts=int(data.get("endDateUnix") or data.get("endTimestamp") or 0),
                )
            except (TypeError, ValueError):
                continue
        return out

    async def get_balance_allowance(self, wallet_address: str) -> float:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            data = await self._get_json(
                session,
                f"{self.clob_url}/balance-allowance",
                params={"address": wallet_address, "asset_type": "COLLATERAL"},
            )
        raw = float((data or {}).get("balance") or 0)
        return raw / 1e6

    async def get_orders(self, wallet_address: str) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            data = await self._get_json(session, f"{self.clob_url}/orders", params={"address": wallet_address})
        return data if isinstance(data, list) else data.get("data", []) if data else []

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.delete(f"{self.clob_url}/orders/{order_id}") as resp:
                payload = await resp.json()
                return payload

    async def get_trades(self, wallet_address: str) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            data = await self._get_json(session, f"{self.clob_url}/trades", params={"address": wallet_address})
        return data if isinstance(data, list) else data.get("data", []) if data else []

    async def place_order(
        self,
        wallet_address: str,
        signature: str,
        market_id: str,
        side: str,
        amount_usd: float,
        price: float,
        proxy_wallet: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "status": "simulated",
                "order_id": f"dry-{market_id}-{side}",
                "filled_price": price,
            }

        payload = {
            "market_id": market_id,
            "side": side,
            "amount": amount_usd,
            "price": price,
            "wallet": wallet_address,
            "signature": signature,
            "signature_type": 2,
            "proxy_wallet": proxy_wallet,
        }
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for _ in range(3):
                try:
                    async with session.post(f"{self.clob_url}/orders", json=payload) as resp:
                        data = await resp.json()
                        if resp.status < 400:
                            return data
                except aiohttp.ClientError:
                    await asyncio.sleep(1)
        return {"status": "failed", "error": "order_failed"}

    async def close_position(
        self,
        wallet_address: str,
        signature: str,
        market_id: str,
        side: str,
        amount_usd: float,
        price: float,
        proxy_wallet: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        opposite = "NO" if side == "YES" else "YES"
        return await self.place_order(
            wallet_address=wallet_address,
            signature=signature,
            market_id=market_id,
            side=opposite,
            amount_usd=amount_usd,
            price=price,
            proxy_wallet=proxy_wallet,
            dry_run=dry_run,
        )
