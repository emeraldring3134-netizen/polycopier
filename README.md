# polymarket-copy-bot

Polymarket 智能钱包跟单机器人（代理钱包 funder + MetaMask 签名模式）。

---

## 1. 程序原理（先看这个）

### 1.1 账户模型

本程序严格按 Polymarket 常见实盘模式实现：

- **MetaMask/EOA 钱包私钥**：只负责签名。
- **Polymarket 代理钱包（funder）**：真实持币账户，充值余额和真实持仓都在这里。
- 程序初始化 CLOB 客户端时使用：
  - `signature_type=2`
  - `funder=<代理钱包地址>`
  - 使用私钥派生 API 凭证 `create_or_derive_api_creds()`。

### 1.2 交易闭环

每轮扫描逻辑：

1. 拉取聪明钱包持仓（候选信号）
2. 先做基础过滤（仓位、价格偏移、到期时间）
3. 对过滤后的候选持仓做**综合评分**（不是信念度硬过滤）
4. 只取评分 Top-N（默认 8）进入跟单
5. 下单前检查：余额、最小股数、冲突仓位、重复单、滑点等
6. 持仓监控实时价格，更新浮盈亏，按追踪止盈/止损/超时退出

### 1.3 为什么这样更稳

- 余额/持仓从 funder 账户取，避免 signer 地址查错。
- 每轮从 trades 重建本地 open positions，减小状态漂移。
- pending 订单状态跟踪 + 超时处理。
- KEEPALIVE 与错误日志可配合守护进程稳定运行。

---

## 2. 架构总览

```text
main.py              # 程序入口 + 主循环
secret_store.py      # 加密输入/解密加载私钥和funder
wallet.py            # 本地签名
polymarket_client.py # CLOB/Gamma/Data API 封装
strategy.py          # 候选信号综合评分 + Top-N选择
risk_manager.py      # 风控检查
executor.py          # 下单/平仓/持仓同步/盈亏更新
tracker.py           # 聪明钱包追踪
storage.py           # 本地状态缓存
logger.py            # 日志
notifier.py          # 飞书通知
hourly_report.py     # 小时报表
send-feishu.py       # 发送飞书消息
config.yaml          # 策略参数
```

---

## 3. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 4. 私钥 + funder 输入（加密存储）

> 这是你要求的“一个命令行流程输入并密码保护”。

初始化加密文件（首次执行一次）：

```bash
python3 main.py --init-secrets --secrets-file secrets.enc.json
```

程序会交互要求输入：

1. MetaMask 私钥
2. 代理钱包 funder 地址
3. 加密密码（输入两次确认）

结果：

- 生成 `secrets.enc.json`（密文文件，权限 600）
- 私钥不会明文落盘

运行时解密：

```bash
python3 main.py --config config.yaml --secrets-file secrets.enc.json
```

启动后会要求输入解密密码；解密后私钥只在内存使用。

### 4.1 内存安全说明（best effort）

程序会尝试：

- 关闭 core dump
- `mlockall` 锁定内存页面（防交换）
- `prctl(PR_SET_DUMPABLE=0)` 降低被非授权进程调试读取风险

> 注意：Linux 用户态无法做到 100% 防所有 root 级攻击，上述为实用强化措施。

---

## 5. 运行

```bash
python3 main.py \
  --config config.yaml \
  --secrets-file secrets.enc.json \
  --rpc-url https://polygon-rpc.com
```

调试模式：

```bash
python3 main.py --config config.yaml --secrets-file secrets.enc.json --dry-run
```

---

## 6. 策略参数（重点）

`config.yaml` 中关键项：

- `strategy.top_n_wallet_positions`：综合评分后取前 N（默认 8）
- `filters.min_position_size_usd`：最小仓位
- `position.copy_ratio`：跟单比例
- `position.max_single_position_usd`：单笔上限
- `position.max_total_exposure_usd`：总暴露上限
- `position.min_order_shares`：最小 5 股
- `position.reserve_balance_usd`：预留余额

---

## 7. 日志与状态文件

- `logs/live-YYYY-MM-DD.log`
- `logs/error-YYYY-MM-DD.log`
- `open-positions.json`
- `tracked-markets.json`

---

## 8. 常见问题

### Q1：为什么余额和持仓可能查不到？
请确认初始化输入的是 **funder 地址**，不是 MetaMask 地址。

### Q2：为什么不下单？
常见原因：

- 预算不足（预留余额后可用资金不足）
- 股数 < 5（被风控拦截）
- 市场冲突/重复跟单
- 滑点超过阈值

### Q3：我只想重新录入私钥和funder
重新执行：

```bash
python3 main.py --init-secrets --secrets-file secrets.enc.json
```
