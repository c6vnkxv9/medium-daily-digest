# Medium 每日新文 → 摘要 → Discord

每天台灣時間 **12:00**（UTC 04:00）檢查指定 Medium RSS；若有**最近 24 小時內**、且尚未處理的新文，以 Claude 產繁體中文摘要，經 Discord Incoming Webhook 推播，並寫入 DynamoDB 去重。

## 架構

```
EventBridge cron(0 4 * * ? *)
        ↓
     Lambda (Python 3.12)
        ├─ Secrets Manager（Claude / Discord webhook / Medium 目標）
        ├─ GET Medium RSS → 最近 24h 過濾
        ├─ DynamoDB 去重與寫入
        ├─ Claude Messages API
        └─ Discord Webhook
```

## 專案結構

```
src/
  handler.py          # Lambda 入口（handler → process_once）
  rss.py              # RSS fetch / parse / 24h filter / HTML→純文字
  summarize.py        # Claude 摘要（zh-TW）
  discord_notify.py   # Discord Incoming Webhook
  store.py            # DynamoDB 去重
  secrets.py          # Secrets Manager
  timeutil.py         # pubDate、24h 時間窗、Taipei 顯示
template.yaml         # SAM（Lambda + DynamoDB + 排程 + 錯誤警報）
samconfig.toml        # SAM 預設參數
events/test-event.json
scripts/smoke_check.py
requirements.txt      # 刻意幾乎空白（執行期只用 stdlib + boto3）
.env.example
```

## 前置準備

1. 確認 RSS 可開：

```bash
curl -sL -A "MediumDailyDigest/1.0" \
  "https://medium.com/feed/@YOUR_MEDIUM_USERNAME" | head -c 500
```

2. 準備 [Anthropic API Key](https://console.anthropic.com/)
3. Discord：伺服器設定 → 整合 → Webhook → 新增 → 複製 URL
4. 可選：本機各測一次（勿把 token 寫進 repo）：

```bash
# Claude
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $CLAUDE_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-5","max_tokens":64,"messages":[{"role":"user","content":"用繁中回：ok"}]}'

# Discord（建議帶 User-Agent；Lambda 亦同，避免 Cloudflare 1010）
curl -X POST "$DISCORD_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "User-Agent: MediumDailyDigest/1.0" \
  -d '{"content":"digest test"}'
```

5. 在 AWS Secrets Manager（建議 `ap-northeast-1`）建立 JSON secret：

```json
{
  "CLAUDE_API_KEY": "...",
  "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/...",
  "MEDIUM_USERNAME": "YOUR_MEDIUM_USERNAME"
}
```

也可改放 `"MEDIUM_RSS_URL": "https://medium.com/feed/@YOUR_MEDIUM_USERNAME"`（有設時優先於 username）。記下 ARN，部署時傳入 `SecretArn`。

## 本機設定

複製 `.env.example` → `.env`（勿提交）：

| 鍵 | 用途 |
|----|------|
| `MEDIUM_USERNAME` 或 `MEDIUM_RSS_URL` | RSS 目標（可覆寫 Secret 內同名鍵） |
| `SECRET_ARN` | Secrets Manager ARN |
| `DDB_TABLE_NAME` | 部署後為 `medium_daily_digest` |
| `CLAUDE_MODEL` | 可選；預設 `claude-sonnet-4-5` |
| `AWS_REGION` | 建議 `ap-northeast-1` |
| `CLAUDE_API_KEY` / `DISCORD_WEBHOOK_URL` | 僅方便本機 curl 或複製進 Secret；**不會**被執行期覆寫 |

`python handler.py` 會自動載入 repo 根目錄 `.env`（不覆寫已存在的環境變數）。Claude／Discord 金鑰一律從 Secrets Manager 讀取。

## 部署（SAM）

前置：AWS CLI、[SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)、可用的 AWS 憑證。Docker 可選（給 `sam local`）。

```bash
# 第一次建議先關閉排程，只手動測
sam build
sam deploy --guided \
  --parameter-overrides \
    "SecretArn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:YOUR_SECRET" \
    "EnableSchedule=false"

# 驗證通過後再開排程
sam deploy --parameter-overrides \
  "SecretArn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:YOUR_SECRET" \
  "EnableSchedule=true"
```

可選參數：`ClaudeModel`（預設 `claude-sonnet-4-5`）。

手動 invoke：

```bash
aws lambda invoke \
  --function-name medium-daily-digest \
  --region ap-northeast-1 \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/digest-out.json && cat /tmp/digest-out.json
```

## 本機執行

需具備讀 Secret + DynamoDB 權限的 AWS 憑證，以及已部署的 table／secret。

```bash
# 完整 pipeline
cd src && python handler.py

# 僅測真實 RSS（不需 AWS）
cd src && python -c "
from rss import fetch_rss, parse_items, filter_recent
xml = fetch_rss('https://medium.com/feed/@YOUR_MEDIUM_USERNAME')
items = parse_items(xml)
print('total', len(items))
for a in items[:3]:
    print(a.published_at, a.title[:60], a.url)
print('recent_24h', len(filter_recent(items)))
"

# 離線 smoke（假 RSS／24h 窗／HTML→純文字）
python3 scripts/smoke_check.py

# sam local（DynamoDB／Secrets 仍需真實 AWS）
sam build
sam local invoke DigestFunction -e events/test-event.json
```

## 行為

| 項目 | 說明 |
|------|------|
| 時間窗 | 只處理 `pubDate` 落在最近 **24 小時**內的文章（非日曆「今日」） |
| 去重 | DynamoDB `article_id`（RSS guid，否則正規化 link）；`status=done` 則 skip；條件寫入永不覆寫 done |
| 無新文 | 成功結束、不推播 |
| Discord | `標題\n\n摘要\n\n連結`（約 1900 字元截斷；帶 `User-Agent`） |
| 回傳 body | `{ checked, new, notified, skipped, errors, taipei_date, window_hours }` |

例：中午 12:00 掃過後，當日 15:00 才發的文，隔天 12:00 仍在 24h 窗內 → 會通知（若尚未 `done`）。

## 驗收

1. 手動 invoke：RSS 有「最近 24h」新文 → DB 一筆、Discord 收到摘要＋連結
2. 再 invoke：同一篇不再推播
3. 無新文／皆已 done：成功、不報錯、不推播
4. 排程於台北 12:00 觸發（CloudWatch log）
5. 金鑰不在程式碼與 log 明文

端到端重測：刪除對應 DynamoDB item（`article_id`）後再 invoke。

## IAM 與資源

由 `template.yaml` 建立：

- **Lambda** `medium-daily-digest`（Python 3.12、Timeout 60s、Memory 256 MB）
- **DynamoDB** `medium_daily_digest`（PK `article_id`，PAY_PER_REQUEST）
- **EventBridge** `cron(0 4 * * ? *)`（可由 `EnableSchedule` 關閉）
- **CloudWatch 警報** `medium-daily-digest-errors`（Errors ≥ 1）

Lambda 執行角色僅：`secretsmanager:GetSecretValue`（該 Secret）、`dynamodb:GetItem`／`PutItem`（該表）、CloudWatch Logs。
