# Medium 每日新文 → 摘要 → LINE 通知

每天台灣時間 **12:00**（UTC 04:00）檢查指定 Medium RSS；若有當日尚未處理的新文，寫入 DynamoDB、用 Claude 產繁體中文摘要，並以 LINE Messaging API 推播。

## 架構

```
EventBridge cron(0 4 * * ? *)
        ↓
     Lambda (Python 3.12)
        ├─ Secrets Manager（Claude / LINE）
        ├─ GET Medium RSS
        ├─ DynamoDB 去重與寫入
        ├─ Claude Messages API
        └─ LINE Push Message
```

## Phase 0 — 帳號與金鑰

1. 確認 RSS 可開：

```bash
curl -sL -A "MediumDailyDigest/1.0" "https://medium.com/feed/@h9r2sx0m" | head -c 500
```

2. 準備 [Anthropic API Key](https://console.anthropic.com/)
3. 建立 [LINE Messaging API](https://developers.line.biz/) Channel，加好友後取得 `userId`（Webhook 可先關；用 push 不需回覆）
4. 本機各測一次（勿把 token 寫進 repo）：

```bash
# Claude
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $CLAUDE_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-5","max_tokens":64,"messages":[{"role":"user","content":"用繁中回：ok"}]}'

# LINE push
curl -X POST https://api.line.me/v2/bot/message/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \
  -d "{\"to\":\"$LINE_USER_ID\",\"messages\":[{\"type\":\"text\",\"text\":\"digest test\"}]}"
```

5. 在 AWS Secrets Manager 建立 secret（JSON）：

```json
{
  "CLAUDE_API_KEY": "...",
  "LINE_CHANNEL_ACCESS_TOKEN": "...",
  "LINE_USER_ID": "..."
}
```

記下 ARN，部署時傳入 `SecretArn`。

## 專案結構

```
src/
  handler.py       # Lambda 入口
  rss.py           # RSS fetch / parse / 台北今日 filter
  summarize.py     # Claude 摘要
  line_notify.py   # LINE push
  store.py         # DynamoDB
  secrets.py       # Secrets Manager
  timeutil.py      # Asia/Taipei
template.yaml      # SAM
events/test-event.json
```

## 部署（SAM）

前置：AWS CLI、[SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)、Docker（可選，給 `sam local`）。

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

可選參數：`MediumRssUrl`、`ClaudeModel`（預設 `claude-sonnet-4-5`）。

手動 invoke：

```bash
aws lambda invoke \
  --function-name medium-daily-digest \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/digest-out.json && cat /tmp/digest-out.json
```

## 本機執行（同一套程式）

需要可用的 AWS 憑證（讀 Secret + DynamoDB），以及已部署的 table／secret，或本機 mock。

```bash
export MEDIUM_RSS_URL="https://medium.com/feed/@h9r2sx0m"
export DDB_TABLE_NAME="medium_daily_digest"
export SECRET_ARN="arn:aws:secretsmanager:..."
export CLAUDE_MODEL="claude-sonnet-4-5"
export AWS_REGION="ap-northeast-1"

cd src && python handler.py
```

僅測 RSS 解析（不需 AWS／金鑰）：

```bash
cd src && python -c "
from rss import fetch_rss, parse_items, filter_taipei_today
xml = fetch_rss('https://medium.com/feed/@h9r2sx0m')
items = parse_items(xml)
print('total', len(items))
for a in items[:3]:
    print(a.published_at, a.title[:60], a.url)
print('today', len(filter_taipei_today(items)))
"
```

離線 smoke（假 RSS／時區／HTML→純文字）：

```bash
python3 scripts/smoke_check.py
```

`sam local invoke`（仍需 AWS 連 DynamoDB／Secrets，或另設 local 替身）：

```bash
sam build
sam local invoke DigestFunction -e events/test-event.json
```

## 行為摘要

| 步驟 | 說明 |
|------|------|
| 當日 | 以 `Asia/Taipei` 的 calendar date 比對 `pubDate` |
| 去重 | `GetItem` 且 `status=done` → skip；`PutItem` 條件避免覆寫 done |
| 無新文 | 成功結束、不推播 |
| LINE 內文 | `標題\n\n摘要\n\n連結` |
| 回傳 | `{ checked, new, notified, skipped, errors, taipei_date }` |

## 驗收

1. 手動 invoke：RSS 有「今日」新文 → DB 一筆、手機收到摘要＋連結  
2. 再 invoke：同一篇不再推播  
3. 無新文：成功、不報錯、不推播  
4. 排程於台北 12:00 觸發（CloudWatch log 時間戳）  
5. 金鑰不在程式碼與 log 明文  

端到端可用舊文：暫時改程式把 filter 換成指定日期，或在測完後刪除對應 DynamoDB item 後重跑。

## IAM（由 SAM 產生）

- `secretsmanager:GetSecretValue`（該 Secret）  
- DynamoDB 該 table 讀寫（SAM `DynamoDBCrudPolicy`）  
- CloudWatch Logs  
- Alarm：`medium-daily-digest-errors`（Errors ≥ 1）  
