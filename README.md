# polymarket-copy-bot

Polymarket 智能钱包跟单机器人（优化版）示例实现。

## 1. 目录结构

```text
polymarket-copy-bot/
├── main.py
├── config.yaml
├── wallet.py
├── polymarket_client.py
├── strategy.py
├── risk_manager.py
├── executor.py
├── tracker.py
├── storage.py
├── logger.py
└── utils.py
```

## 2. 环境要求

- Linux（OpenCloudOS 9 可运行）
- Python 3.10+

## 3. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. 私钥配置（仅 ENV）

```bash
export PRIVATE_KEY=0xYOUR_PRIVATE_KEY
```

> 程序不会将私钥写入磁盘。

## 5. 启动

```bash
python3 main.py \
  --config config.yaml \
  --private-key PRIVATE_KEY \
  --rpc-url https://polygon-rpc.com \
  --dry-run
```

参数：

- `--config` 配置文件路径
- `--private-key` 私钥所在环境变量名（如 `PRIVATE_KEY`）
- `--proxy-wallet` 代理钱包（可选）
- `--rpc-url` Polygon RPC 地址
- `--dry-run` 模拟交易模式

## 6. 产物

- `logs/bot.log`：扫描与交易日志
- `logs/error.log`：错误日志
- `positions.json`：本地持仓与已跟单信号缓存

## 7. 注意

- 接口字段在 Polymarket 版本变化时可能调整，`polymarket_client.py` 使用了兼容性解析与重试。
- 实盘前请务必先用 `--dry-run` 和小额度测试。
