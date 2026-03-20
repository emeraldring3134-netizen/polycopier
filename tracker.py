from __future__ import annotations

import asyncio
from typing import Iterable

from polymarket_client import PolymarketClient, SmartWalletPosition


class SmartWalletTracker:
    def __init__(self, client: PolymarketClient, max_wallets: int) -> None:
        self.client = client
        self.max_wallets = max_wallets

    async def fetch_positions(self, wallets: Iterable[str]) -> list[SmartWalletPosition]:
        wallet_list = list(wallets)[: self.max_wallets]
        tasks = [self.client.get_wallet_positions(w) for w in wallet_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[SmartWalletPosition] = []
        for item in results:
            if isinstance(item, Exception):
                continue
            out.extend(item)
        return out
