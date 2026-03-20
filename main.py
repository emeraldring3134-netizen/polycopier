from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

import yaml

from executor import Executor
from logger import setup_logger
from polymarket_client import PolymarketClient
from risk_manager import RiskManager
from storage import Storage
from strategy import Strategy
from tracker import SmartWalletTracker
from wallet import Wallet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Smart Wallet Copy Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--private-key",
        default="PRIVATE_KEY",
        help="Environment variable key that stores private key, e.g. PRIVATE_KEY",
    )
    parser.add_argument("--rpc-url", default="https://polygon-rpc.com", help="Polygon RPC URL")
    parser.add_argument("--proxy-wallet", default=None, help="Optional proxy wallet address")
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders without placing real trades")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run_bot(cfg: dict[str, Any], args: argparse.Namespace, logger: logging.Logger) -> None:
    wallet = Wallet(private_key_env=args.private_key, signature_type=2)
    client = PolymarketClient(rpc_url=args.rpc_url)
    storage = Storage("positions.json")
    risk = RiskManager(cfg=cfg, storage=storage)
    strategy = Strategy(cfg=cfg)
    tracker = SmartWalletTracker(client=client, max_wallets=cfg["strategy"]["max_tracked_wallets"])
    executor = Executor(
        client=client,
        wallet=wallet,
        risk=risk,
        storage=storage,
        cfg=cfg,
        logger=logger,
        dry_run=args.dry_run,
    )

    logger.info("bot started wallet=%s proxy=%s dry_run=%s", wallet.address, args.proxy_wallet, args.dry_run)
    interval = int(cfg["strategy"]["scan_interval_seconds"])

    while True:
        try:
            smart_positions = await tracker.fetch_positions(cfg.get("wallets", []))
            market_ids = sorted({p.market_id for p in smart_positions})
            market_map = await client.get_market_data_batch(market_ids)
            exposure = risk.current_exposure()
            signals = strategy.build_signals(smart_positions, market_map, current_total_exposure=exposure)

            logger.info(
                "scan wallets=%d smart_positions=%d market_data=%d signals=%d exposure=%.4f",
                len(cfg.get("wallets", [])),
                len(smart_positions),
                len(market_map),
                len(signals),
                exposure,
            )

            for s in signals:
                await executor.execute_signal(s)

            smart_state = {(p.market_id, p.side): (not p.smart_wallet_closed) for p in smart_positions}
            await executor.evaluate_exits(smart_state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("main loop error: %s", exc)

        await asyncio.sleep(interval)


def main() -> None:
    args = parse_args()
    logger = setup_logger()
    cfg = load_config(args.config)
    asyncio.run(run_bot(cfg, args, logger))


if __name__ == "__main__":
    main()
