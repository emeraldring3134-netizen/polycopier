from __future__ import annotations

import argparse
import asyncio
import os
import subprocess

from polymarket_client import PolymarketClient
from wallet import Wallet


async def build_report(client: PolymarketClient, wallet_addr: str) -> str:
    balance = await client.get_balance_allowance(wallet_addr)
    trades = await client.get_trades(wallet_addr)
    total_notional = 0.0
    for t in trades:
        total_notional += float(t.get("size") or t.get("shares") or 0) * float(t.get("price") or 0)
    return f"[Hourly] wallet={wallet_addr} balance=${balance:.2f} trade_notional=${total_notional:.2f}"


async def main_async(args: argparse.Namespace) -> None:
    wallet = Wallet(args.private_key, private_key_gpg=args.private_key_gpg)
    client = PolymarketClient(args.rpc_url)
    report = await build_report(client, wallet.address)
    if args.feishu_webhook:
        subprocess.check_call(["python3", "send-feishu.py", "--webhook", args.feishu_webhook, "--text", report])
    else:
        print(report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", default="PRIVATE_KEY")
    parser.add_argument("--private-key-gpg", default=".env.gpg")
    parser.add_argument("--rpc-url", default="https://polygon-rpc.com")
    parser.add_argument("--feishu-webhook", default=os.getenv("FEISHU_WEBHOOK", ""))
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
