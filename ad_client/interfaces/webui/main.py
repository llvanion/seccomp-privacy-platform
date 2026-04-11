from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ad_client.adapters.gateway.http_gateway_adapter import GatewayRequestError
from ad_client.app.bootstrap import build_advertiser_client_service

_, service = build_advertiser_client_service()
app = FastAPI(title="Advertiser PSI Client", version="0.1.0")


class ExposureRecordPayload(BaseModel):
    user_id: str
    timestamp: int | None = None
    tag: str | None = None
    labels: dict[str, Any] | None = None


class PsiRunPayload(BaseModel):
    job_id: str
    start_ts: int
    end_ts: int
    caller: str
    exposure_records: list[ExposureRecordPayload] = Field(default_factory=list)
    bucket_by: str | None = None
    k: int = 20
    n: int = 5
    value_mode: str = "count"
    out_dir: str | None = None


def _run(callable_fn):
    try:
        return callable_fn()
    except GatewayRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>Advertiser PSI Client</title>
  <link rel="icon" href="data:,">
  <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
  <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
  <style>
    :root {
      --bg: linear-gradient(135deg, #f5f1e8 0%, #d6e7f5 100%);
      --panel: rgba(255, 255, 255, 0.92);
      --ink: #19222b;
      --muted: #5f6d78;
      --accent: #c56025;
      --accent-dark: #8e3c11;
      --line: rgba(25, 34, 43, 0.12);
      --ok: #1f7a52;
      --err: #b33a3a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Noto Serif SC", "Songti SC", serif;
      color: var(--ink);
      background: var(--bg);
    }
    .shell {
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 20px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: 0 18px 40px rgba(25, 34, 43, 0.08);
      padding: 22px;
      backdrop-filter: blur(14px);
    }
    h1 {
      margin: 0 0 10px;
      font-size: 40px;
      line-height: 1.05;
    }
    .lead, .muted {
      color: var(--muted);
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      font-size: 14px;
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--ok);
      box-shadow: 0 0 0 6px rgba(31, 122, 82, 0.12);
    }
    .dot.offline {
      background: var(--err);
      box-shadow: 0 0 0 6px rgba(179, 58, 58, 0.12);
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }
    .section-title {
      margin: 0 0 16px;
      font-size: 22px;
    }
    label {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      color: var(--muted);
    }
    input, textarea, select {
      width: 100%;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 12px;
      font: inherit;
      background: rgba(255,255,255,0.95);
      color: var(--ink);
    }
    textarea {
      min-height: 180px;
      resize: vertical;
      font-family: "SFMono-Regular", Consolas, monospace;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
      margin-bottom: 14px;
    }
    .field {
      margin-bottom: 14px;
    }
    button {
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 12px 18px;
      font: inherit;
      cursor: pointer;
    }
    button.secondary {
      background: #284b63;
    }
    button:disabled {
      opacity: 0.6;
      cursor: progress;
    }
    pre {
      margin: 0;
      padding: 16px;
      border-radius: 14px;
      background: #1d2730;
      color: #dce8f2;
      overflow-x: auto;
      font-size: 13px;
    }
    .hint {
      font-size: 13px;
      color: var(--muted);
      margin-top: 8px;
    }
    @media (max-width: 900px) {
      .hero, .grid, .row { grid-template-columns: 1fr; }
      h1 { font-size: 32px; }
    }
  </style>
</head>
<body>
  <div id="app" class="shell">
    <div class="hero">
      <div class="card">
        <h1>广告商 PSI 归因客户端</h1>
        <p class="lead">上传曝光集合，触发与平台购买集合的隐私集合求交，并只查看经过阈值发布和审计保护后的聚合结果。</p>
        <div class="status">
          <span class="dot" :class="{ offline: !gatewayOnline }"></span>
          Gateway {{ gatewayOnline ? 'Online' : 'Offline' }}
        </div>
      </div>
      <div class="card">
        <h2 class="section-title">运行说明</h2>
        <p class="muted">支持 JSON 或 CSV 格式曝光集合。JSON 需为数组；CSV 至少包含 <code>user_id</code> 列，可选 <code>timestamp</code> 和 <code>tag</code>。</p>
        <p class="muted">当前 WebUI 会在浏览器本地解析文件，再把结构化记录发到网关。</p>
      </div>
    </div>

    <div class="grid">
      <section class="card">
        <h2 class="section-title">发起任务</h2>
        <div class="row">
          <div class="field">
            <label>Job ID</label>
            <input v-model="runForm.job_id">
          </div>
          <div class="field">
            <label>Caller</label>
            <input v-model="runForm.caller">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label>Start TS</label>
            <input v-model.number="runForm.start_ts" type="number">
          </div>
          <div class="field">
            <label>End TS</label>
            <input v-model.number="runForm.end_ts" type="number">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label>K Threshold</label>
            <input v-model.number="runForm.k" type="number">
          </div>
          <div class="field">
            <label>Frequency Cap (N)</label>
            <input v-model.number="runForm.n" type="number">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label>Bucket By</label>
            <input v-model="runForm.bucket_by" placeholder="例如 tag">
          </div>
          <div class="field">
            <label>Value Mode</label>
            <select v-model="runForm.value_mode">
              <option value="count">count</option>
              <option value="sum">sum</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>曝光集合文件</label>
          <input type="file" accept=".json,.csv" @change="onFileChange">
          <div class="hint">{{ fileHint }}</div>
        </div>
        <div class="field">
          <label>曝光集合预览</label>
          <textarea v-model="runForm.preview"></textarea>
        </div>
        <button @click="submitRun" :disabled="runLoading">{{ runLoading ? '提交中...' : '上传曝光集合并发起归因任务' }}</button>
        <div class="hint">结果只展示聚合报告，不返回用户级交集明细。</div>
      </section>

      <section class="card">
        <h2 class="section-title">查询结果</h2>
        <div class="row">
          <div class="field">
            <label>Job ID</label>
            <input v-model="resultJobId">
          </div>
          <div class="field" style="display:flex;align-items:end;">
            <button class="secondary" @click="fetchResult" :disabled="resultLoading">{{ resultLoading ? '查询中...' : '读取已发布结果' }}</button>
          </div>
        </div>
        <pre>{{ prettyResult }}</pre>
      </section>
    </div>
  </div>

  <script>
    const { createApp, ref, reactive, computed, onMounted } = Vue;

    function parseCsv(text) {
      const lines = text.trim().split(/\\r?\\n/).filter(Boolean);
      if (lines.length < 2) return [];
      const headers = lines[0].split(',').map(item => item.trim());
      return lines.slice(1).map((line) => {
        const values = line.split(',');
        const row = {};
        headers.forEach((header, index) => {
          row[header] = (values[index] || '').trim();
        });
        return row;
      });
    }

    createApp({
      setup() {
        const gatewayOnline = ref(true);
        const runLoading = ref(false);
        const resultLoading = ref(false);
        const fileHint = ref('尚未选择文件');
        const resultJobId = ref('ad-job-demo-001');
        const resultData = ref({ message: '尚未查询结果' });
        const parsedRecords = ref([]);
        const runForm = reactive({
          job_id: 'ad-job-demo-001',
          caller: 'advertiser-demo',
          start_ts: 1704067200,
          end_ts: 1706745600,
          k: 20,
          n: 5,
          bucket_by: 'tag',
          value_mode: 'count',
          preview: JSON.stringify([
            { user_id: 'u-1', timestamp: 1704067201, tag: 'campaign-a' },
            { user_id: 'u-2', timestamp: 1704067202, tag: 'campaign-b' }
          ], null, 2)
        });

        const prettyResult = computed(() => JSON.stringify(resultData.value, null, 2));

        const checkHealth = async () => {
          try {
            await axios.get('/api/health');
            gatewayOnline.value = true;
          } catch (_) {
            gatewayOnline.value = false;
          }
        };

        const onFileChange = async (event) => {
          const file = event.target.files[0];
          if (!file) return;
          const text = await file.text();
          let records;
          if (file.name.toLowerCase().endsWith('.json')) {
            records = JSON.parse(text);
          } else if (file.name.toLowerCase().endsWith('.csv')) {
            records = parseCsv(text);
          } else {
            resultData.value = { error: '仅支持 JSON 或 CSV 文件' };
            return;
          }
          parsedRecords.value = records;
          runForm.preview = JSON.stringify(records, null, 2);
          fileHint.value = `已载入 ${file.name}，共 ${records.length} 条记录`;
        };

        const submitRun = async () => {
          runLoading.value = true;
          try {
            const records = parsedRecords.value.length ? parsedRecords.value : JSON.parse(runForm.preview);
            const payload = {
              job_id: runForm.job_id,
              caller: runForm.caller,
              start_ts: runForm.start_ts,
              end_ts: runForm.end_ts,
              k: runForm.k,
              n: runForm.n,
              value_mode: runForm.value_mode,
              bucket_by: runForm.bucket_by || null,
              exposure_records: records,
            };
            const res = await axios.post('/api/psi/run', payload);
            resultData.value = res.data;
            resultJobId.value = runForm.job_id;
          } catch (error) {
            resultData.value = error.response?.data || { message: String(error) };
          }
          runLoading.value = false;
        };

        const fetchResult = async () => {
          resultLoading.value = true;
          try {
            const res = await axios.get(`/api/psi/result/${encodeURIComponent(resultJobId.value)}`);
            resultData.value = res.data;
          } catch (error) {
            resultData.value = error.response?.data || { message: String(error) };
          }
          resultLoading.value = false;
        };

        onMounted(() => {
          checkHealth();
          setInterval(checkHealth, 30000);
        });

        return {
          gatewayOnline,
          runForm,
          runLoading,
          resultLoading,
          resultJobId,
          prettyResult,
          fileHint,
          onFileChange,
          submitRun,
          fetchResult,
        };
      }
    }).mount('#app');
  </script>
</body>
</html>
"""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return _run(lambda: service.health())


@app.post("/api/psi/run")
def psi_run(payload: PsiRunPayload) -> dict[str, Any]:
    result = _run(
        lambda: service.run_psi(
            job_id=payload.job_id,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            caller=payload.caller,
            exposure_records=[record.model_dump() for record in payload.exposure_records],
            k=payload.k,
            n=payload.n,
            value_mode=payload.value_mode,
            bucket_by=payload.bucket_by,
            out_dir=payload.out_dir,
        )
    )
    return {
        "job_id": result.job_id,
        "released": result.released,
        "reason_code": result.reason_code,
        "report": result.report,
    }


@app.get("/api/psi/result/{job_id}")
def psi_result(job_id: str) -> dict[str, Any]:
    result = _run(lambda: service.get_result(job_id))
    return {
        "job_id": result.job_id,
        "released": result.released,
        "reason_code": result.reason_code,
        "report": result.report,
    }
