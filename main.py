from __future__ import annotations

# 标准库：参数解析、异步调度、日志类型。
import argparse
import asyncio
import logging
import time
from typing import Any

# 第三方：YAML 配置读取。
import yaml

# 业务模块：执行器、日志、通知、客户端、风控、密钥管理、存储、策略、跟踪与钱包。
from executor import Executor
from logger import setup_logger
from notifier import FeishuNotifier
from polymarket_client import PolymarketClient
from risk_manager import RiskManager
from secret_store import init_secret_file, load_secret_file
from storage import Storage
from strategy import Strategy
from tracker import SmartWalletTracker
from wallet import Wallet


class IterationAdapter(logging.LoggerAdapter):
    """为每条日志补充 iteration 字段，方便按轮次排查问题。"""

    def process(self, msg, kwargs):
        # 若外部未传 extra，则补一个空字典。
        kwargs.setdefault("extra", {})
        # 若外部未传 iteration，则使用当前适配器里的 iteration。
        kwargs["extra"].setdefault("iteration", self.extra.get("iteration", "-"))
        return msg, kwargs


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Polymarket Smart Wallet Copy Bot")
    # 配置文件路径。
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    # 密文密钥文件路径。
    parser.add_argument("--secrets-file", default="secrets.enc.json", help="Encrypted secrets file")
    # 初始化密文模式：交互输入私钥和 funder 后写入密文文件。
    parser.add_argument("--init-secrets", action="store_true", help="Interactive setup for private key + funder and encrypt")
    # Polygon RPC 地址。
    parser.add_argument("--rpc-url", default="https://polygon-rpc.com", help="Polygon RPC URL")
    # Dry-run：模拟交易，不发真实单。
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders without placing real trades")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    """读取 YAML 配置并转为字典。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def keepalive(logger: logging.Logger) -> None:
    """每 60 秒输出一次心跳日志，便于看门狗判断进程存活。"""
    while True:
        logger.info("KEEPALIVE", extra={"iteration": "-"})
        await asyncio.sleep(60)


async def run_bot(cfg: dict[str, Any], args: argparse.Namespace, logger: logging.Logger) -> None:
    """机器人主循环：初始化依赖、按轮扫描并执行策略。"""
    # 启动时输入密码，解密出私钥与 funder；私钥仅在内存中使用。
    secret_bundle = load_secret_file(args.secrets_file)
    # 用解密后的私钥创建签名钱包。
    wallet = Wallet(private_key=secret_bundle.private_key, signature_type=2)
    # 用 signer 私钥 + funder 地址初始化客户端；signature_type 固定为 2。
    client = PolymarketClient(
        rpc_url=args.rpc_url,
        timeout_seconds=15,
        private_key=wallet.private_key,
        proxy_wallet=secret_bundle.funder,
        signature_type=2,
    )
    # 本地状态存储：持仓与已跟踪市场。
    storage = Storage("open-positions.json", "tracked-markets.json")
    # 风控模块。
    risk = RiskManager(cfg=cfg, storage=storage)
    # 策略模块。
    strategy = Strategy(cfg=cfg)
    # 跟踪模块：按配置的钱包数和 60 天胜率过滤。
    tracker = SmartWalletTracker(
        client=client,
        max_wallets=cfg["strategy"]["max_tracked_wallets"],
        min_wallet_win_rate_60d=cfg["filters"].get("min_wallet_win_rate_60d", 0.55),
    )
    # 飞书通知器。
    notifier = FeishuNotifier(cfg.get("notification", {}).get("feishu_webhook", ""))
    # 执行器：负责同步持仓、下单、平仓、挂单检查。
    executor = Executor(
        client=client,
        wallet=wallet,
        risk=risk,
        storage=storage,
        cfg=cfg,
        logger=logger,
        dry_run=args.dry_run,
        proxy_wallet=secret_bundle.funder,
        notifier=notifier,
    )

    # 记录启动信息：签名钱包地址、funder 地址和 dry-run 状态。
    logger.info("bot started wallet=%s funder=%s dry_run=%s", wallet.address, secret_bundle.funder, args.dry_run, extra={"iteration": 0})
    # 读取扫描间隔。
    interval = int(cfg["strategy"]["scan_interval_seconds"])
    # 后台启动 KEEPALIVE。
    asyncio.create_task(keepalive(logger))
    # 轮次计数器。
    iteration = 0

    # 无限循环：每轮执行一次扫描与风控交易。
    while True:
        started_at = time.monotonic()
        iteration += 1
        iter_logger = IterationAdapter(logger, {"iteration": iteration})
        try:
            await executor.check_pending_orders(iteration)
            await executor.sync_positions_from_trades(iteration)

            funder_balance = await client.get_balance_allowance(wallet.address)
            current_positions = storage.get_positions()
            iter_logger.info("funder snapshot balance=%.4f positions=%d", funder_balance, len(current_positions))

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

        spent = time.monotonic() - started_at
        await asyncio.sleep(max(0.0, interval - spent))


def main() -> None:
    """程序入口：支持初始化密钥或正常启动两种模式。"""
    args = parse_args()
    # 若传入 --init-secrets，则走一次性密钥录入流程。
    if args.init_secrets:
        init_secret_file(args.secrets_file)
        print(f"secrets initialized: {args.secrets_file}")
        return

    # 初始化日志系统。
    logger = setup_logger()
    # 手动创建事件循环，便于设置全局异常处理。
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        # 捕获未处理的异步异常并写日志。
        logger.error("unhandled loop exception: %s", context, extra={"iteration": "-"})

    # 注册事件循环异常处理器。
    loop.set_exception_handler(handle_exception)
    try:
        # 读取配置并进入主循环。
        cfg = load_config(args.config)
        loop.run_until_complete(run_bot(cfg, args, logger))
    except Exception as exc:  # noqa: BLE001
        # 兜底异常日志。
        logger.exception("uncaughtException: %s", exc, extra={"iteration": "-"})
        raise


if __name__ == "__main__":
    # 以脚本方式运行时进入 main。
    main()
