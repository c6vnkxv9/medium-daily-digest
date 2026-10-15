# CLAUDE.md

本檔案提供在此儲存庫撰寫／修改程式時的指引（給 AI 助手使用）。

## 這是什麼

以 SAM 部署的 AWS Lambda（Python 3.12），每日排程一次：抓取 Medium RSS、只保留**最近 24 小時內**且尚未處理的文章、以 Claude Messages API 產繁體中文摘要、經 Discord Incoming Webhook 推播，並寫入 DynamoDB 去重。文件與程式註解使用繁體中文（zh-TW）；編輯文件／prompt 時維持同樣語系。

## 常用指令

```bash
# 離線煙霧測試（不需 AWS／API 金鑰）
python3 scripts/smoke_check.py

# 僅對真實 feed 做 RSS 檢查（不需 AWS）
cd src && python -c "
from rss import fetch_rss, parse_items, filter_recent
xml = fetch_rss('https://medium.com/feed/@YOUR_MEDIUM_USERNAME')
items = parse_items(xml)
print('total', len(items))
for a in items[:3]:
    print(a.published_at, a.title[:60], a.url)
print('recent_24h', len(filter_recent(items)))
"

# 本機完整執行（需已部署 Secret + DynamoDB 的 AWS 憑證）
# 複製 .env.example → .env，填入 MEDIUM_USERNAME（或 MEDIUM_RSS_URL）、SECRET_ARN 等
cd src && python handler.py

# SAM 建置／部署
sam build
sam deploy --guided --parameter-overrides \
  "SecretArn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:YOUR_SECRET" \
  "EnableSchedule=false"

# sam local invoke（DynamoDB／Secrets 仍需真實 AWS）
sam build
sam local invoke DigestFunction -e events/test-event.json

# 已部署 Lambda 手動 invoke
aws lambda invoke --function-name medium-daily-digest --region ap-northeast-1 \
  --payload '{}' --cli-binary-format raw-in-base64-out \
  /tmp/digest-out.json && cat /tmp/digest-out.json
```

沒有 pytest — 唯一自動化檢查是 `scripts/smoke_check.py`（純 assert）。儲存庫內沒有 lint／format 設定。

## 架構

單一 pipeline：每個外部依賴一個模組，由 `src/handler.py` 串起：

```
src/handler.py         Lambda 進入點（handler → process_once）；resolve_rss_url
                       本機 .env／環境變數優先，否則用 Secret；每篇文章獨立
                       try/except，單篇失敗不阻擋其餘；回傳 body 含
                       {checked, new, notified, skipped, errors, taipei_date, window_hours}
src/rss.py             fetch_rss（urllib）→ parse_items（ElementTree；content:encoded
                       失敗則退回 description）→ filter_recent（預設 24h）
                       → load_recent_articles；html_to_text
src/timeutil.py        pubDate 解析（RFC2822／ISO）、Asia/Taipei 顯示、
                       is_within_last_hours（時間窗唯一權威來源）
src/summarize.py       urllib 呼叫 Claude Messages API（無 anthropic SDK）；
                       固定 zh-TW system／user prompt
src/discord_notify.py  格式「title\n\nsummary\n\nurl」；User-Agent；約 1900 字元截斷
src/store.py           is_done()；put_done()／put_error() 皆用 ConditionExpression，
                       永不覆寫 status=done
src/secrets.py         單一 JSON：CLAUDE_API_KEY／DISCORD_WEBHOOK_URL，
                       以及可選 MEDIUM_USERNAME／MEDIUM_RSS_URL；模組層快取
```

## 關鍵不變式

- **去重鍵是 DynamoDB `article_id`**（RSS guid，沒有則用正規化 link）。`put_done`／`put_error` 條件為 `attribute_not_exists OR status <> done` — 不要改成無條件 `put_item`。
- **候選以「最近 24 小時」為時間窗**（`timeutil.is_within_last_hours`／`rss.filter_recent`），不是日曆「台北今日」。EventBridge `cron(0 4 * * ? *)` = UTC 04:00 = 台北 12:00；改排程請從台北時間換算。
- **錯誤以單篇文章為單位且非致命**：`process_once` 對每篇 catch、寫入 `status=error`（不蓋掉 `done`），繼續下一篇。
- **執行期無第三方依賴** — `rss`／`summarize`／`discord_notify` 用 stdlib `urllib`；只用 Lambda runtime 的 `boto3`／`botocore`。`requirements.txt` 刻意幾乎空白。
- **Medium 帳號不硬編碼** — 本機 `.env` 的 `MEDIUM_USERNAME`／`MEDIUM_RSS_URL`；上雲放同一份 Secret JSON。不要在程式或 SAM 參數寫死 `@username`。
- **密鑰只從 Secrets Manager 讀** — `get_secrets()` 一律讀 `CLAUDE_API_KEY`／`DISCORD_WEBHOOK_URL`（不從 `.env` 覆寫這兩項）。永不硬編碼憑證、勿提交真實 `.env`。

## 設定

`.env.example` 鍵：`MEDIUM_USERNAME`、`DDB_TABLE_NAME`、`SECRET_ARN`、`CLAUDE_MODEL`、`AWS_REGION`；可選 `CLAUDE_API_KEY`／`DISCORD_WEBHOOK_URL` 僅方便本機 curl 或複製進 Secret。`handler._load_dotenv` 本機載入 `.env`（不覆寫已存在變數）；勿印出 `.env` 內容。

RSS 解析優先序（`resolve_rss_url`）：環境變數 `MEDIUM_RSS_URL` → Secret `MEDIUM_RSS_URL` → 環境變數 `MEDIUM_USERNAME` → Secret `MEDIUM_USERNAME`。

## 基礎設施（`template.yaml`）

- Lambda `DigestFunction`／`medium-daily-digest`：Python 3.12、Timeout 60s、Memory 256 MB
- DynamoDB `medium_daily_digest`：PK `article_id`，PAY_PER_REQUEST
- EventBridge 排程（`EnableSchedule` 可關）；CloudWatch 警報 `medium-daily-digest-errors`
- IAM 僅該表 `GetItem`／`PutItem` 與該 secret `GetSecretValue`
- 每次調用可能串行多篇文章（RSS → Claude → Discord）；新增耗時呼叫前留意 60 秒上限
- 首次部署／手動測試用 `EnableSchedule=false`，端到端成功後再改 `true`
