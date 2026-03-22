# polymarket-copy-bot

Polymarket 智能钱包跟单机器人（MetaMask 签名 + funder 代理钱包模式）。

## 核心机制

- 使用 MetaMask 私钥签名（`signature_type=2`）。
- 使用 Polymarket 后台生成的代理钱包 `funder` 作为真实余额与持仓账户。
- 每轮先同步 funder 实际持仓，再做选股与跟单，避免重复下单。

## 本次重点优化

1. **funder 持仓去重**：若 funder 已持有该市场，直接跳过，防止重复下单。
2. **价格区间过滤**：默认仅跟单 `0.2 ~ 0.8` 的市场（可配置）。
3. **funder 余额/持仓查询加强**：每轮记录 funder 余额与当前持仓数量。
4. **钱包轮换支持**：可随时 `--init-secrets` 重新录入私钥与 funder；下次启动自动用新私钥重新派生 API 凭证。
5. **到期时间过滤默认 12h**：过滤短期高波动市场。
6. **综合评分增强**：加入钱包 60 天胜率 + 同市场同方向多钱包共识权重。
7. **固定 10 分钟扫描**：默认每 600 秒扫描，按耗时补偿睡眠，保证节奏稳定。
8. **平仓逻辑强化**：平仓增加重试，提升执行成功率。

## 快速开始

### 1) 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 初始化或更新私钥/funder（交互式）

```bash
python3 main.py --init-secrets --secrets-file secrets.enc.json
```

会提示输入：

- MetaMask 私钥
- funder 代理钱包地址
- 加密密码（两次）

> 若你更换钱包/私钥，重复执行该命令即可，程序会在下次启动时自动使用新配置并重新派生 API 信息。

### 3) 启动机器人

```bash
python3 main.py --config config.yaml --secrets-file secrets.enc.json
```

调试（不真实下单）：

```bash
python3 main.py --config config.yaml --secrets-file secrets.enc.json --dry-run
```

## 关键配置（`config.yaml`）

- `strategy.scan_interval_seconds`：默认 `600`（10分钟）
- `strategy.top_n_wallet_positions`：评分后 Top-N（默认 8）
- `filters.min_market_price` / `filters.max_market_price`：默认 `0.2 ~ 0.8`
- `filters.min_time_to_expiry_minutes`：默认 `720`（12小时）
- `position.min_order_shares`：默认最少 5 股

## 程序架构

- `main.py`：入口、调度、周期扫描
- `polymarket_client.py`：Polymarket API / CLOB 访问
- `tracker.py`：聪明钱包跟踪与胜率过滤
- `strategy.py`：过滤 + 综合评分 + TopN
- `risk_manager.py`：冲突/重复/滑点/持仓校验
- `executor.py`：下单、平仓、持仓同步、挂单处理
- `storage.py`：本地状态持久化
- `secret_store.py`：加密保存并解密私钥/funder
- `logger.py`：日志

## 安全说明

- 私钥不明文落盘，密文保存在 `secrets.enc.json`。
- 解密后只在内存使用，并进行 best-effort 进程加固（禁 core dump / mlockall / prctl）。
