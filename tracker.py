from __future__ import annotations

import asyncio
from typing import Iterable

from polymarket_client import PolymarketClient, SmartWalletPosition


class SmartWalletTracker:
    def __init__(self, client: PolymarketClient, max_wallets: int, min_wallet_win_rate_60d: float) -> None:
        self.client = client
        self.max_wallets = max_wallets
        self.min_wallet_win_rate_60d = min_wallet_win_rate_60d

    async def fetch_positions(self, wallets: Iterable[str]) -> list[SmartWalletPosition]:
        wallet_list = list(wallets)[: self.max_wallets]

        score_tasks = [self.client.get_wallet_win_rate_60d(w) for w in wallet_list]
        score_results = await asyncio.gather(*score_tasks, return_exceptions=True)
        filtered_wallets: list[str] = []
        for wallet, score in zip(wallet_list, score_results):
            if isinstance(score, Exception):
                continue
            if score >= self.min_wallet_win_rate_60d:
                filtered_wallets.append(wallet)

        tasks = [self.client.get_wallet_positions(w) for w in filtered_wallets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[SmartWalletPosition] = []
        for item in results:
            if isinstance(item, Exception):
                continue
            out.extend(item)
        return out
