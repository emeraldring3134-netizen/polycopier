# polymarket-copy-bot

Polymarket 智能钱包跟单机器人（修复增强版，Linux/OpenCloudOS9）。

## 已修复关键问题

- 余额精度统一为 **USDC 6 位小数**（`/1e6`），避免余额放大 100 倍。
- 增加全局异常处理与 `KEEPALIVE` 日志（每 60 秒）防止看门狗误杀。
- `tracked-markets.json` 持久化去重，重启后仍能防重复下单。
- 每轮扫描前从 CLOB `trades` 重建 `open-positions.json`，减少本地状态漂移。
- 持仓按最新价格实时计算浮盈亏，并写回 `open-positions.json`。

## 新增增强能力

- 飞书价格预警（±15% 可配置）。
- 追踪止盈（最高盈利>=30% 且回撤10%触发）+ 固定止损（-20%）。
- 订单状态跟踪、30分钟超时取消+重试一次。
- 钱包 60 天胜率过滤（<55% 不跟）。
- 多策略模式（激进/标准/保守）随总暴露动态切换。
- 日志文件按天切割：`logs/live-YYYY-MM-DD.log`、`logs/error-YYYY-MM-DD.log`。

## 目录

```text
main.py
config.yaml
wallet.py
polymarket_client.py
strategy.py
risk_manager.py
executor.py
tracker.py
storage.py
logger.py
notifier.py
utils.py
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 私钥安全

推荐：将私钥放入 `.env.gpg`（仅内存解密，不写磁盘）

```bash
gpg --encrypt --recipient <YOUR_KEY_ID> .env
```

`.env.gpg` 内容可为：

```text
PRIVATE_KEY=0x...
```

## 启动

```bash
python3 main.py \
  --config config.yaml \
  --private-key PRIVATE_KEY \
  --private-key-gpg .env.gpg \
  --proxy-wallet 0xYourProxy \
  --rpc-url https://polygon-rpc.com \
  --dry-run
```

## 代理钱包（MetaMask 登录）关键说明

- MetaMask/EOA 私钥仅用于签名。
- Polymarket 资金账户使用平台生成的 **proxy/funder 地址**，余额与持仓都应查询该地址。
- 程序已按此模式初始化 CLOB 客户端：`signature_type=2` + `funder=PROXY_WALLET`，并在启动时通过私钥 `create_or_derive_api_creds()` 派生 API key。

