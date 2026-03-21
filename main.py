from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

import yaml

from executor import Executor
from logger import setup_logger
from notifier import FeishuNotifier
from polymarket_client import PolymarketClient
from risk_manager import RiskManager
from storage import Storage
from strategy import Strategy
from tracker import SmartWalletTracker
from wallet import Wallet


class IterationAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        kwargs.setdefault("extra", {})
        kwargs["extra"].setdefault("iteration", self.extra.get("iteration", "-"))
        return msg, kwargs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Smart Wallet Copy Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--private-key", default="PRIVATE_KEY", help="Environment variable key that stores private key")
    parser.add_argument("--private-key-gpg", default=".env.gpg", help="Encrypted private key file path")
    parser.add_argument("--rpc-url", default="https://polygon-rpc.com", help="Polygon RPC URL")
    parser.add_argument("--proxy-wallet", default=None, help="Optional proxy wallet address")
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders without placing real trades")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def keepalive(logger: logging.Logger) -> None:
    while True:
        logger.info("KEEPALIVE", extra={"iteration": "-"})
        await asyncio.sleep(60)


async def run_bot(cfg: dict[str, Any], args: argparse.Namespace, logger: logging.Logger) -> None:
    wallet = Wallet(private_key_env=args.private_key, signature_type=2, private_key_gpg=args.private_key_gpg)
    client = PolymarketClient(
        rpc_url=args.rpc_url,
        timeout_seconds=15,
        private_key=wallet.private_key,
        proxy_wallet=args.proxy_wallet,
        signature_type=2,
    )
    storage = Storage("open-positions.json", "tracked-markets.json")
    risk = RiskManager(cfg=cfg, storage=storage)
    strategy = Strategy(cfg=cfg)
    tracker = SmartWalletTracker(
        client=client,
        max_wallets=cfg["strategy"]["max_tracked_wallets"],
        min_wallet_win_rate_60d=cfg["filters"].get("min_wallet_win_rate_60d", 0.55),
    )
    notifier = FeishuNotifier(cfg.get("notification", {}).get("feishu_webhook", ""))
    executor = Executor(
        client=client,
        wallet=wallet,
        risk=risk,
        storage=storage,
        cfg=cfg,
        logger=logger,
        dry_run=args.dry_run,
        proxy_wallet=args.proxy_wallet,
        notifier=notifier,
    )

    logger.info("bot started wallet=%s proxy=%s dry_run=%s", wallet.address, args.proxy_wallet, args.dry_run, extra={"iteration": 0})
    interval = int(cfg["strategy"]["scan_interval_seconds"])
    asyncio.create_task(keepalive(logger))
    iteration = 0

    while True:
        iteration += 1
        iter_logger = IterationAdapter(logger, {"iteration": iteration})
        try:
            await executor.check_pending_orders(iteration)
            await executor.sync_positions_from_trades(iteration)

            smart_positions = await tracker.fetch_positions(cfg.get("wallets", []))
            market_ids = sorted({p.market_id for p in smart_positions})
            market_map = await client.get_market_data_batch(market_ids)
            exposure = risk.current_exposure()
            signals = strategy.build_signals(smart_positions, market_map, current_total_exposure=exposure)

            iter_logger.info(
                "scan wallets=%d smart_positions=%d market_data=%d signals=%d exposure=%.4f",
                len(cfg.get("wallets", [])),
                len(smart_positions),
                len(market_map),
                len(signals),
                exposure,
            )

            for s in signals:
                await executor.execute_signal(s, iteration)

            smart_state = {(p.market_id, p.side): (not p.smart_wallet_closed) for p in smart_positions}
            market_names = {mid: m.market_name for mid, m in market_map.items()}
            await executor.evaluate_exits(smart_state, market_names, iteration)
        except Exception as exc:  # noqa: BLE001
            iter_logger.exception("main loop error: %s", exc)

        await asyncio.sleep(interval)


def main() -> None:
    args = parse_args()
    logger = setup_logger()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        logger.error("unhandled loop exception: %s", context, extra={"iteration": "-"})

    loop.set_exception_handler(handle_exception)
    try:
        cfg = load_config(args.config)
        loop.run_until_complete(run_bot(cfg, args, logger))
    except Exception as exc:  # noqa: BLE001
        logger.exception("uncaughtException: %s", exc, extra={"iteration": "-"})
        raise


if __name__ == "__main__":
    main()
