#!/usr/bin/env python3
"""Operator dashboard server — serves a web UI over local pipeline sidecar artifacts."""
import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_observability_dashboard import build_dashboard
from check_observability_alerts import build_alert_report

CACHE_TTL = 5.0

# ---------------------------------------------------------------------------
# HTML dashboard (single-file, no external deps)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Pipeline — Operator Dashboard</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;
  --ok:#3fb950;--warn:#d29922;--err:#f85149;--acc:#58a6ff;--font:ui-monospace,
  SFMono-Regular,Menlo,Monaco,Consolas,monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:13px/1.5 var(--font);
  min-height:100vh;padding:16px}
a{color:var(--acc)}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;
  border-radius:12px;font-size:11px;font-weight:600;letter-spacing:.3px}
.badge.ok{background:rgba(63,185,80,.15);color:var(--ok)}
.badge.warn{background:rgba(210,153,34,.15);color:var(--warn)}
.badge.err{background:rgba(248,81,73,.15);color:var(--err)}
.badge.unknown{background:rgba(139,148,158,.12);color:var(--muted)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;display:inline-block}
header{display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;background:var(--card);border:1px solid var(--border);
  border-radius:8px;margin-bottom:12px;gap:12px;flex-wrap:wrap}
.logo{font-size:15px;font-weight:700;color:var(--text)}
.logo span{color:var(--acc)}
.meta-row{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.meta{font-size:11px;color:var(--muted)}
.meta b{color:var(--text)}
.countdown{font-size:11px;color:var(--muted);margin-left:auto}
.grid{display:grid;gap:12px;margin-bottom:12px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:1fr 1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:900px){.g3,.g4{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.g2,.g3,.g4{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:14px;overflow:hidden}
.card h3{font-size:10px;text-transform:uppercase;letter-spacing:.8px;
  color:var(--muted);margin-bottom:10px;display:flex;align-items:center;gap:8px}
.alert-card{border-left:3px solid var(--border)}
.alert-card.firing.err{border-left-color:var(--err)}
.alert-card.firing.warn{border-left-color:var(--warn)}
.alert-card.ok-state{border-left-color:var(--ok)}
.alert-name{font-weight:600;font-size:12px;margin-bottom:4px}
.alert-msg{font-size:11px;color:var(--muted);line-height:1.4}
.check-row{display:flex;flex-wrap:wrap;gap:6px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:4px 8px;color:var(--muted);font-size:10px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
td{padding:5px 8px;border-bottom:1px solid rgba(48,54,61,.5)}
tr:last-child td{border-bottom:none}
.bar-row{display:flex;align-items:center;gap:8px;padding:4px 0}
.bar-label{width:160px;font-size:12px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;flex-shrink:0}
.bar-track{flex:1;height:8px;background:rgba(48,54,61,.8);border-radius:4px;
  overflow:hidden;display:flex;gap:1px}
.bar-ok{background:var(--ok);height:100%;border-radius:4px 0 0 4px}
.bar-err{background:var(--err);height:100%;border-radius:0 4px 4px 0}
.bar-counts{font-size:11px;color:var(--muted);white-space:nowrap;min-width:70px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.loading{display:flex;align-items:center;justify-content:center;height:80px;
  color:var(--muted);font-size:12px}
.spinner{width:14px;height:14px;border:2px solid var(--border);
  border-top-color:var(--acc);border-radius:50%;animation:spin .7s linear infinite;
  margin-right:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.error-msg{padding:12px;background:rgba(248,81,73,.1);border:1px solid var(--err);
  border-radius:6px;color:var(--err);font-size:12px}
.section-label{font-size:10px;text-transform:uppercase;letter-spacing:.8px;
  color:var(--muted);margin:16px 0 8px}
.stage-timeline{max-height:280px;overflow-y:auto}
.tl-row{display:flex;gap:8px;align-items:baseline;padding:3px 0;
  border-bottom:1px solid rgba(48,54,61,.4)}
.tl-row:last-child{border-bottom:none}
.tl-ts{font-size:10px;color:var(--muted);min-width:82px;flex-shrink:0}
.tl-stage{min-width:180px;flex-shrink:0;font-size:12px}
.tl-role{min-width:50px;font-size:11px;color:var(--muted)}
.tl-dur{min-width:60px;font-size:11px;color:var(--muted);text-align:right}
.tl-rc{font-size:11px;color:var(--muted)}
.wf-state{font-size:13px;font-weight:600}
.wf-action{font-size:11px;padding:3px 10px;border-radius:10px;display:inline-block;
  background:rgba(88,166,255,.1);color:var(--acc)}
</style>
</head>
<body>
<header>
  <div class="logo">🔒 <span>Privacy Pipeline</span> Operator Dashboard</div>
  <div class="meta-row" id="meta-row">
    <div class="loading"><div class="spinner"></div>loading…</div>
  </div>
  <div class="countdown" id="countdown"></div>
</header>
<div id="main"><div class="loading"><div class="spinner"></div>loading…</div></div>

<script>
"use strict";
let _timer = null;
let _countdown = 15;

function statusClass(s){
  if(!s) return "unknown";
  s = s.toLowerCase();
  if(s==="ok"||s==="completed"||s==="allow") return "ok";
  if(s==="warn"||s==="warning") return "warn";
  if(s==="error"||s==="err"||s==="failed"||s==="reject"||s==="denied"||s==="deny") return "err";
  return "unknown";
}
function badge(s, label){
  const c = statusClass(s);
  return `<span class="badge ${c}"><span class="dot"></span>${label||s||"—"}</span>`;
}
function esc(s){ return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;"); }
function ms(v){ return v!=null ? `${v}ms` : "—"; }
function fmtTs(s){
  if(!s) return "—";
  try{
    const d=new Date(s);
    return d.toLocaleTimeString("en-GB",{hour12:false,hour:"2-digit",
      minute:"2-digit",second:"2-digit"});
  }catch{return s.slice(0,19).replace("T"," ");}
}

function renderHeader(data){
  const s = statusClass(data.overall_status);
  const d = data.dashboard||{};
  const sc = d.summary||{};
  const parts = [
    badge(data.overall_status),
    `<span class="meta">job <b>${esc(data.job_id||"—")}</b></span>`,
    data.caller ? `<span class="meta">caller <b>${esc(data.caller)}</b></span>` : "",
    data.tenant_id ? `<span class="meta">tenant <b>${esc(data.tenant_id)}</b></span>` : "",
    `<span class="meta">updated <b>${fmtTs(data.generated_at_utc)}</b></span>`,
    sc.total_events!=null ? `<span class="meta">${sc.total_events} events</span>` : "",
  ].filter(Boolean).join(" ");
  document.getElementById("meta-row").innerHTML = parts;
}

function renderAlerts(alerts_data){
  if(!alerts_data||!alerts_data.alerts) return `<div class="loading">No alert data</div>`;
  const items = alerts_data.alerts.map(a=>{
    const firing = a.firing;
    const sc = firing ? statusClass(a.severity) : "ok-state";
    const firingClass = firing ? `firing ${statusClass(a.severity)}` : "ok-state";
    const b = firing ? badge(a.severity,"FIRING") : badge("ok","ok");
    return `<div class="card alert-card ${firingClass}">
      <div class="alert-name">${esc(a.alert_id)} ${b}</div>
      <div class="alert-msg">${esc(a.message)}</div>
    </div>`;
  }).join("");
  return `<div class="card"><h3>Alerts
    ${badge(alerts_data.overall_status)} <span style="color:var(--muted);font-size:10px;">${alerts_data.firing_count||0} firing / ${alerts_data.alert_count||0} total</span>
  </h3><div class="grid g4">${items||"<div>—</div>"}</div></div>`;
}

function renderHealth(health){
  if(!health||!health.checks) return "";
  const sum = health.summary||{};
  const checks = health.checks.map(c=>{
    return badge(c.status, c.name);
  }).join(" ");
  return `<div class="card"><h3>Platform Health ${badge(sum.status)} <span style="color:var(--muted);font-size:10px;">ok:${sum.ok||0} warn:${sum.warn||0} err:${sum.error||0}</span></h3>
    <div class="check-row">${checks||"<span style='color:var(--muted)'>—</span>"}</div>
  </div>`;
}

function renderStageSummary(panels){
  if(!panels||!panels.stage_summary) return "";
  const rows = (panels.stage_summary.rows||[]).map(r=>{
    const total = r.total||1;
    const okPct = Math.round((r.ok||0)/total*100);
    const errPct = Math.round((r.error||0)/total*100);
    return `<div class="bar-row">
      <div class="bar-label">${esc(r.stage)}</div>
      <div class="bar-track">
        <div class="bar-ok" style="width:${okPct}%"></div>
        <div class="bar-err" style="width:${errPct}%"></div>
      </div>
      <div class="bar-counts">${badge("ok",r.ok)} ${r.error?badge("err",r.error):""}</div>
    </div>`;
  }).join("");
  return `<div class="card"><h3>Stage Summary</h3>${rows||"<div style='color:var(--muted)'>No data</div>"}</div>`;
}

function renderStageDuration(panels){
  if(!panels||!panels.stage_duration) return "";
  const rows = (panels.stage_duration.rows||[]).map(r=>`
    <tr>
      <td>${esc(r.stage)}</td>
      <td class="num">${r.sample_count}</td>
      <td class="num">${ms(r.min_ms)}</td>
      <td class="num">${ms(r.mean_ms)}</td>
      <td class="num">${ms(r.p50_ms)}</td>
      <td class="num">${ms(r.p95_ms)}</td>
      <td class="num">${ms(r.max_ms)}</td>
    </tr>`).join("");
  return `<div class="card"><h3>Stage Duration</h3>
    <table><thead><tr><th>Stage</th><th>N</th><th>min</th><th>mean</th><th>p50</th><th>p95</th><th>max</th></tr></thead>
    <tbody>${rows||"<tr><td colspan='7' style='color:var(--muted)'>No timing data</td></tr>"}</tbody></table>
  </div>`;
}

function renderReleaseOutcomes(panels){
  if(!panels||!panels.release_outcomes) return "";
  const rows = (panels.release_outcomes.rows||[]).map(r=>`
    <tr>
      <td>${esc(r.tenant_id)}</td>
      <td class="num">${badge("ok",r.ok_count)}</td>
      <td class="num">${r.error_count?badge("err",r.error_count):badge("ok",0)}</td>
      <td>${badge(r.last_status||"unknown")}</td>
      <td>${fmtTs(r.last_ts_utc)}</td>
    </tr>`).join("");
  const label = panels.release_outcomes.row_count===0
    ? "<tr><td colspan='5' style='color:var(--muted)'>No release events</td></tr>"
    : rows;
  return `<div class="card"><h3>Release Outcomes</h3>
    <table><thead><tr><th>Tenant</th><th>OK</th><th>Errors</th><th>Last</th><th>Time</th></tr></thead>
    <tbody>${label}</tbody></table>
  </div>`;
}

function renderFailureSummary(panels){
  if(!panels||!panels.failure_summary) return "";
  const rows = (panels.failure_summary.rows||[]).map(r=>`
    <tr>
      <td>${badge("err",r.stage||"—")}</td>
      <td>${esc(r.caller||"—")}</td>
      <td>${esc(r.role||"—")}</td>
      <td style="color:var(--err)">${esc(r.reason_code||"—")}</td>
      <td>${ms(r.duration_ms)}</td>
      <td>${fmtTs(r.ts_utc)}</td>
    </tr>`).join("");
  const label = panels.failure_summary.row_count===0
    ? "<tr><td colspan='6' style='color:var(--ok)'>✓ No failures</td></tr>"
    : rows;
  return `<div class="card"><h3>Failure Summary</h3>
    <table><thead><tr><th>Stage</th><th>Caller</th><th>Role</th><th>Reason</th><th>Dur</th><th>Time</th></tr></thead>
    <tbody>${label}</tbody></table>
  </div>`;
}

function renderWorkflowStatus(ws){
  if(!ws||ws.available===false) return "";
  const action = ws.recommended_action;
  return `<div class="card"><h3>Workflow Status</h3>
    <div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px">
      <span class="wf-state">${badge(ws.state||"unknown")}</span>
      ${ws.job_id?`<span class="meta">job <b>${esc(ws.job_id)}</b></span>`:""}
      ${ws.last_exit_code!=null?`<span class="meta">exit <b>${ws.last_exit_code}</b></span>`:""}
      ${ws.receipt_count!=null?`<span class="meta">${ws.receipt_count} receipt(s)</span>`:""}
      ${ws.last_updated_at_utc?`<span class="meta">at <b>${fmtTs(ws.last_updated_at_utc)}</b></span>`:""}
    </div>
    ${action?`<span class="wf-action">→ ${esc(action)}</span>`:""}
  </div>`;
}

function renderStageTimeline(panels){
  if(!panels||!panels.stage_timeline) return "";
  const rows = (panels.stage_timeline.rows||[]).map(r=>`
    <div class="tl-row">
      <span class="tl-ts">${fmtTs(r.ts_utc)}</span>
      <span class="tl-stage">${badge(r.status,"●")} ${esc(r.stage||"—")}</span>
      <span class="tl-role">${esc(r.role||"")}</span>
      <span class="tl-dur">${ms(r.duration_ms)}</span>
      <span class="tl-rc">${esc(r.reason_code||"")}</span>
    </div>`).join("");
  return `<div class="card" style="grid-column:1/-1"><h3>Stage Timeline (${panels.stage_timeline.row_count||0} events)</h3>
    <div class="stage-timeline">${rows||"<div style='color:var(--muted)'>No events</div>"}</div>
  </div>`;
}

function render(data){
  const d = data.dashboard||{};
  const panels = d.panels||{};
  const alerts = data.alerts||null;
  const health = data.health||null;
  const ws = data.workflow_status||null;
  renderHeader(data);
  document.getElementById("main").innerHTML = [
    renderAlerts(alerts),
    renderHealth(health),
    `<div class="grid g3">`,
      renderStageSummary(panels),
      renderStageDuration(panels),
      renderWorkflowStatus(ws)||renderReleaseOutcomes(panels),
    `</div>`,
    `<div class="grid g2">`,
      renderReleaseOutcomes(panels),
      renderFailureSummary(panels),
    `</div>`,
    `<div class="grid">`,
      renderStageTimeline(panels),
    `</div>`,
  ].filter(Boolean).join("\n");
}

async function load(){
  try{
    const resp = await fetch("/v1/dashboard", {cache:"no-store"});
    const data = await resp.json();
    if(data.error){
      document.getElementById("main").innerHTML =
        `<div class="error-msg">API error: ${esc(JSON.stringify(data.error))}</div>`;
      return;
    }
    render(data);
  }catch(e){
    document.getElementById("main").innerHTML =
      `<div class="error-msg">Could not reach /v1/dashboard: ${esc(String(e))}</div>`;
  }
}

function tick(){
  _countdown--;
  if(_countdown<=0){
    _countdown=15;
    load();
  }
  document.getElementById("countdown").textContent=`↺ ${_countdown}s`;
}

load();
_timer=setInterval(tick,1000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache_data: dict[str, Any] | None = None
_cache_ts: float = 0.0


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _build_data(out_base: Path) -> dict[str, Any]:
    observability_path = out_base / "pipeline_observability.json"
    platform_health_path = out_base / "platform_health.json"
    workflow_status_path = out_base / "query_workflow" / "status.json"

    observability = _load_optional(observability_path)
    platform_health = _load_optional(platform_health_path)
    workflow_status_raw = _load_optional(workflow_status_path)

    dashboard: dict[str, Any] | None = None
    alerts: dict[str, Any] | None = None

    if observability is not None:
        try:
            dashboard = build_dashboard(observability, platform_health=platform_health)
        except Exception as exc:
            dashboard = {"error": str(exc)}
        if dashboard and "error" not in dashboard:
            try:
                alerts = build_alert_report(dashboard, platform_health=platform_health)
            except Exception as exc:
                alerts = {"error": str(exc)}

    health_section: dict[str, Any] | None = None
    if platform_health:
        ph_summary = platform_health.get("summary")
        if isinstance(ph_summary, dict):
            health_section = {
                "summary": ph_summary,
                "checks": platform_health.get("checks") or [],
            }

    workflow_status: dict[str, Any] | None = None
    if workflow_status_raw:
        retry_rec: str | None = None
        retry_eligible: dict[str, Any] | None = None
        receipts_path = out_base / "query_workflow" / "execution_receipts.jsonl"
        try:
            from check_workflow_retry_eligibility import build_eligibility_report, load_jsonl_objects
            receipts: list[dict[str, Any]] = []
            if receipts_path.is_file():
                receipts = load_jsonl_objects(receipts_path)
            retry_eligible = build_eligibility_report(workflow_status_raw, receipts)
            retry_rec = retry_eligible.get("recommended_action")
        except Exception:
            pass
        workflow_status = {
            "available": True,
            "job_id": workflow_status_raw.get("job_id"),
            "state": workflow_status_raw.get("state"),
            "terminal": workflow_status_raw.get("terminal"),
            "last_exit_code": workflow_status_raw.get("last_exit_code"),
            "receipt_count": workflow_status_raw.get("receipt_count"),
            "last_updated_at_utc": workflow_status_raw.get("last_updated_at_utc"),
            "recommended_action": retry_rec,
        }

    scope = {}
    for field in ("job_id", "correlation_id", "caller", "tenant_id", "dataset_id", "service_id"):
        scope[field] = (dashboard or {}).get(field) if dashboard else None

    alert_status = (alerts or {}).get("overall_status", "unknown")
    health_status = ((health_section or {}).get("summary") or {}).get("status", "unknown")
    dash_status = (dashboard or {}).get("summary", {}).get("overall_status", "unknown")

    def _worst(*statuses: str) -> str:
        if any(s == "error" for s in statuses):
            return "error"
        if any(s == "warn" for s in statuses):
            return "warn"
        if all(s == "ok" for s in statuses if s not in ("unknown", "")):
            return "ok"
        return "warn"

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **scope,
        "overall_status": _worst(alert_status, health_status, dash_status),
        "dashboard": dashboard,
        "alerts": alerts,
        "health": health_section,
        "workflow_status": workflow_status,
    }


def get_dashboard_data(out_base: Path) -> dict[str, Any]:
    global _cache_data, _cache_ts
    with _cache_lock:
        now = time.monotonic()
        if _cache_data is None or now - _cache_ts > CACHE_TTL:
            _cache_data = _build_data(out_base)
            _cache_ts = now
        return _cache_data


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_cls, *, out_base: Path, pid_file: str, ready_file: str) -> None:
        self.out_base = out_base
        self.pid_file = pid_file
        self.ready_file = ready_file
        super().__init__(server_address, handler_cls)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress default access log

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = _DASHBOARD_HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif path == "/healthz":
            body = json.dumps({"status": "ok", "schema": "operator_dashboard_health/v1"}).encode()
            self._send(200, "application/json", body)
        elif path == "/v1/dashboard":
            data = get_dashboard_data(self.server.out_base)
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        else:
            body = json.dumps({"error": "not_found", "path": path}).encode()
            self._send(404, "application/json", body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_file(path: str, content: str) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def remove_file(path: str) -> None:
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve the operator dashboard web UI.")
    ap.add_argument("--out-base", required=True, help="Run output directory (contains pipeline_observability.json etc.)")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18094)
    ap.add_argument("--pid-file", default="", help="Write server PID here on start")
    ap.add_argument("--ready-file", default="", help="Write '1' here when server is ready")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_base = Path(args.out_base).expanduser().resolve()
    if not out_base.is_dir():
        raise SystemExit(f"[ERROR] --out-base does not exist: {out_base}")

    server = DashboardServer(
        (args.bind_host, args.port),
        DashboardHandler,
        out_base=out_base,
        pid_file=args.pid_file,
        ready_file=args.ready_file,
    )

    def _shutdown(sig: int, frame: Any) -> None:
        remove_file(args.pid_file)
        remove_file(args.ready_file)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    write_file(args.pid_file, str(os.getpid()))
    write_file(args.ready_file, "1")

    print(json.dumps({
        "status": "started",
        "url": f"http://{args.bind_host}:{args.port}/",
        "out_base": str(out_base),
        "pid": os.getpid(),
    }))
    sys.stdout.flush()

    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
