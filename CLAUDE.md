# CLAUDE.md

本檔案提供在此儲存庫撰寫／修改程式時的指引（給 Claude Code 等 AI 助手使用）。

## 這是什麼

一個以 SAM 部署的 AWS Lambda（Python 3.12），依排程每日執行一次：抓取 Medium RSS、只保留 Asia/Taipei 當日發布的文章、透過 Claude Messages API 以繁體中文摘要每篇新文、經 LINE Messaging API 推播給指定使用者，並寫入 DynamoDB 避免重複通知。文件與程式註解使用繁體中文（zh-TW）；編輯文件／prompt 時請維持同樣語系。

## 常用指令

```bash
# 離線煙霧測試（不需 AWS／API 金鑰）— 解析範例 RSS、檢查日期過濾與 HTML→純文字
python3 scripts/smoke_check.py

# 僅對真實 feed 做 RSS 檢查（不需 AWS）
cd src && python -c "
from rss import fetch_rss, parse_items, filter_taipei_today
xml = fetch_rss('https://medium.com/feed/@h9r2sx0m')
items = parse_items(xml)
print('total', len(items))
for a in items[:3]:
    print(a.published_at, a.title[:60], a.url)
print('today', len(filter_taipei_today(items)))
"

# 本機完整執行（需具備已部署 Secret + DynamoDB 權限的 AWS 憑證）
export MEDIUM_RSS_URL="https://medium.com/feed/@h9r2sx0m"
export DDB_TABLE_NAME="medium_daily_digest"
export SECRET_ARN="arn:aws:secretsmanager:..."
export CLAUDE_MODEL="claude-sonnet-4-5"
export AWS_REGION="ap-northeast-1"
cd src && python handler.py

# SAM 建置／部署
sam build
sam deploy --guided --parameter-overrides \
  "SecretArn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:YOUR_SECRET" \
  "EnableSchedule=false"   # 手動驗證前先關閉排程

# sam local invoke（DynamoDB／Secrets 仍需真實 AWS 存取）
sam build
sam local invoke DigestFunction -e events/test-event.json

# 對已部署的 Lambda 手動 invoke
aws lambda invoke --function-name medium-daily-digest --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/digest-out.json && cat /tmp/digest-out.json
```

沒有 pytest 套件 — 唯一自動化檢查是 `scripts/smoke_check.py`（純 assert、`python3` 進入點）。儲存庫內也沒有 lint／format 設定。

## 架構

單一用途的 pipeline：每個外部依賴一個模組，全部在 `src/handler.py` 串起：

```
src/handler.py      Lambda 進入點（handler → process_once）；每篇文章獨立 try/except，
                     單篇失敗不阻擋其餘；回傳 {checked, new, notified,
                     skipped, errors, taipei_date}
src/rss.py           fetch_rss（urllib GET）→ parse_items（stdlib ElementTree；讀
                     content:encoded，失敗則退回 description）→ filter_taipei_today
src/timeutil.py      所有 Asia/Taipei 日期邏輯（RFC2822／ISO pubDate 解析、「是否為
                     台北今日」比較）— 「今天」的唯一權威來源
src/summarize.py     以 urllib 直接呼叫 Claude Messages API（不依賴 anthropic SDK）；
                     固定 zh-TW 的 system／user prompt 範本
src/line_notify.py   格式化為「title\n\nsummary\n\nurl」並經 LINE push API 推播；
                     截斷摘要以符合 LINE 約 5000 字元文字上限
src/store.py         DynamoDB 去重：is_done() 檢查 status=done；put_done()／put_error()
                     使用 ConditionExpression，確保 status=done 列永不被覆蓋
                     （去重保證），並讓並行 invoke 安全競態
src/secrets.py       從 Secrets Manager 以單一 JSON 讀取 CLAUDE_API_KEY／
                     LINE_CHANNEL_ACCESS_TOKEN／LINE_USER_ID；模組層快取可跨越
                     warm Lambda 調用
```

編輯時請維持的關鍵不變式：
- **去重鍵是 DynamoDB `article_id`**（RSS guid，沒有則用正規化後的 link）。`store.put_done`／`put_error` 依賴條件寫入（`attribute_not_exists OR status <> done`），讓重跑與並行調用安全 — 不要改成無條件的 `put_item`。
- **「今天」一律以 Asia/Taipei 為準**，在 `timeutil.py` 計算，不是 Lambda 的 UTC 執行時間。`template.yaml` 的 EventBridge cron（`cron(0 4 * * ? *)`）是 UTC 04:00 = 台北 12:00；若改排程，請從台北時間換算。
- **錯誤以單篇文章為單位且非致命**：`handler.process_once` 對每篇文章 catch、記錄、寫入 `status=error` 列（同樣有條件保護，不會蓋掉 `done`），然後繼續下一篇，而不是中止整次調用。
- **執行期無第三方依賴** — `rss.py`、`summarize.py`、`line_notify.py` 都用 stdlib `urllib`，不用 `requests`／`anthropic` SDK，以省去 Lambda 打包。只用 Lambda runtime 提供的 `boto3`／`botocore`，`requirements.txt` 刻意幾乎空白 — 除非新依賴確實需要打進 artifact，否則維持現狀。
- 密鑰（Claude API key、LINE token／user id）放在由 SAM 參數 `SecretArn` 指向的單一 Secrets Manager JSON secret — 永不硬編碼憑證或提交 `.env`。

## 基礎設施（SAM／`template.yaml`）

- 單一 Lambda（`DigestFunction`）+ 單一 DynamoDB 表（`medium_daily_digest`，PK `article_id`，PAY_PER_REQUEST）+ EventBridge 排程 + 針對 Lambda Errors 的 CloudWatch 警報。
- `EnableSchedule` 參數開關 EventBridge 觸發 — 首次部署／手動測試用 `false`，確認手動 invoke 端到端成功後再改為 `true`。
- IAM 精確限定此表（`dynamodb:GetItem`／`PutItem`）與此 secret（`secretsmanager:GetSecretValue`），由 SAM 的 `DynamoDBCrudPolicy`／inline statement 產生 — 新增 AWS 呼叫時同樣縮小範圍，勿擴大權限。
