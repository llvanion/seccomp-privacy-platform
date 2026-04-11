# Advertiser PSI Client

`ad_client` 是广告商专用的 PSI 广告归因客户端，只保留两类能力：

- 上传曝光集合并发起归因任务
- 读取任务结果与可发布报告

## CLI

```bash
python ad_client_main.py cli health
python ad_client_main.py cli psi-run \
  --job-id ad-job-001 \
  --start-ts 1704067200 \
  --end-ts 1706745600 \
  --caller advertiser-demo \
  --exposure-file ./exposures.json \
  --bucket-by tag
python ad_client_main.py cli psi-result --job-id ad-job-001
```

## WebUI

```bash
python ad_client_main.py webui --host 127.0.0.1 --port 8081
```

打开 `http://127.0.0.1:8081`。

## 曝光集合格式

JSON 示例：

```json
[
  {
    "user_id": "u-1",
    "timestamp": 1704067201,
    "tag": "campaign-a"
  },
  {
    "user_id": "u-2",
    "timestamp": 1704067202,
    "tag": "campaign-b",
    "labels": {
      "channel": "search"
    }
  }
]
```

CSV 至少需要 `user_id` 列，可选 `timestamp`、`tag`。
