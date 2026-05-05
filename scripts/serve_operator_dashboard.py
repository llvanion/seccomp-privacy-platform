#!/usr/bin/env python3
"""Operator dashboard server — serves a web UI over local pipeline sidecar artifacts."""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from archive_audit_bundle import summarize_mainline_contract
from build_observability_dashboard import build_dashboard
from check_observability_alerts import build_alert_report
from list_query_workflow_status import scan_status_files
from submit_query_workflow import (
    STATUS_SCHEMA as QUERY_WORKFLOW_STATUS_SCHEMA,
    append_jsonl,
    build_command,
    build_receipt,
    build_status,
    json_sha256,
    load_request,
    normalize_request_paths,
    query_workflow_sidecar_paths,
    render_manifest,
    validate_request,
    write_json,
)

CACHE_TTL = 5.0

# ---------------------------------------------------------------------------
# HTML dashboard (single-file, no external deps)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PJC X-UI | Control and Audit Center</title>
<style>
:root{--bg:#0a0f14;--bg2:#0f1722;--panel:#121c28;--panel2:#192636;--line:#243548;
  --text:#e6edf6;--muted:#92a2b6;--ok:#37d67a;--warn:#f2b94b;--err:#ff6b6b;
  --acc:#5ec8ff;--acc2:#1f8fff;--glow:rgba(94,200,255,.18);--font:"Segoe UI",
  "SF Pro Display","Helvetica Neue",sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:
  radial-gradient(circle at top right, rgba(31,143,255,.12), transparent 34%),
  radial-gradient(circle at bottom left, rgba(55,214,122,.08), transparent 26%),
  linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
  color:var(--text);font:13px/1.5 var(--font);min-height:100vh}
a{color:var(--acc)}
.shell{display:grid;grid-template-columns:260px 1fr;min-height:100vh}
@media(max-width:980px){.shell{grid-template-columns:1fr}}
.sidebar{padding:20px 18px;border-right:1px solid rgba(36,53,72,.9);
  background:linear-gradient(180deg, rgba(18,28,40,.96), rgba(10,15,20,.94));
  position:sticky;top:0;height:100vh}
@media(max-width:980px){.sidebar{position:static;height:auto;border-right:none;border-bottom:1px solid rgba(36,53,72,.9)}}
.brand{font-size:22px;font-weight:800;letter-spacing:.6px}
.brand span{color:var(--acc)}
.brand-sub{font-size:11px;color:var(--muted);margin-top:6px;max-width:180px}
.nav{display:grid;gap:8px;margin:28px 0}
.nav a{text-decoration:none;padding:10px 12px;border:1px solid transparent;border-radius:12px;
  color:var(--text);background:rgba(255,255,255,.02)}
.nav a:hover{border-color:rgba(94,200,255,.28);background:rgba(94,200,255,.08)}
.side-note{margin-top:auto;padding:12px;border:1px solid var(--line);border-radius:12px;
  background:rgba(25,38,54,.52);font-size:11px;color:var(--muted)}
.content{padding:20px}
@media(max-width:700px){.content{padding:14px}}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;
  border-radius:12px;font-size:11px;font-weight:600;letter-spacing:.3px}
.badge.ok{background:rgba(63,185,80,.15);color:var(--ok)}
.badge.warn{background:rgba(210,153,34,.15);color:var(--warn)}
.badge.err{background:rgba(248,81,73,.15);color:var(--err)}
.badge.unknown{background:rgba(139,148,158,.12);color:var(--muted)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;display:inline-block}
header{display:flex;align-items:flex-start;justify-content:space-between;padding:18px 20px;
  background:linear-gradient(180deg, rgba(25,38,54,.95), rgba(18,28,40,.92));
  border:1px solid var(--line);border-radius:18px;margin-bottom:16px;gap:16px;flex-wrap:wrap;
  box-shadow:0 18px 48px rgba(0,0,0,.22)}
.hero-title{font-size:28px;font-weight:800;letter-spacing:.2px}
.hero-sub{font-size:12px;color:var(--muted);margin-top:4px}
.meta-row{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:12px}
.meta{font-size:11px;color:var(--muted);font-family:var(--mono)}
.meta b{color:var(--text)}
.countdown{font-size:11px;color:var(--muted);font-family:var(--mono)}
.grid{display:grid;gap:14px;margin-bottom:14px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:1fr 1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:900px){.g3,.g4{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.g2,.g3,.g4{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg, rgba(18,28,40,.95), rgba(14,22,32,.96));
  border:1px solid var(--line);border-radius:18px;padding:16px;overflow:hidden;
  box-shadow:0 16px 36px rgba(0,0,0,.18)}
.card h3{font-size:11px;text-transform:uppercase;letter-spacing:1px;
  color:var(--muted);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.section-title{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;
  color:var(--muted);margin:18px 0 10px}
.hero-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px}
@media(max-width:1100px){.hero-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.hero-grid{grid-template-columns:1fr}}
.hero-card{padding:16px 18px;border-radius:18px;border:1px solid var(--line);
  background:linear-gradient(180deg, rgba(25,38,54,.92), rgba(13,21,31,.92))}
.hero-k{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
.hero-v{font-size:24px;font-weight:800;margin-top:8px}
.hero-subline{margin-top:8px;font-size:12px;color:var(--muted)}
.alert-card{border-left:3px solid var(--border)}
.alert-card.firing.err{border-left-color:var(--err)}
.alert-card.firing.warn{border-left-color:var(--warn)}
.alert-card.ok-state{border-left-color:var(--ok)}
.alert-name{font-weight:600;font-size:12px;margin-bottom:4px}
.alert-msg{font-size:11px;color:var(--muted);line-height:1.4}
.check-row{display:flex;flex-wrap:wrap;gap:6px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:4px 8px;color:var(--muted);font-size:10px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid rgba(36,53,72,.65)}
tr:last-child td{border-bottom:none}
.mono{font-family:var(--mono)}
.bar-row{display:flex;align-items:center;gap:8px;padding:4px 0}
.bar-label{width:160px;font-size:12px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;flex-shrink:0}
.bar-track{flex:1;height:8px;background:rgba(36,53,72,.82);border-radius:4px;
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
.stage-timeline{max-height:280px;overflow-y:auto}
.tl-row{display:flex;gap:8px;align-items:baseline;padding:3px 0;
  border-bottom:1px solid rgba(36,53,72,.56)}
.tl-row:last-child{border-bottom:none}
.tl-ts{font-size:10px;color:var(--muted);min-width:82px;flex-shrink:0}
.tl-stage{min-width:180px;flex-shrink:0;font-size:12px}
.tl-role{min-width:50px;font-size:11px;color:var(--muted)}
.tl-dur{min-width:60px;font-size:11px;color:var(--muted);text-align:right}
.tl-rc{font-size:11px;color:var(--muted)}
.wf-state{font-size:13px;font-weight:600}
.job-form{display:grid;gap:10px}
.field{display:grid;gap:4px}
.field label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.field input{width:100%;background:#0a1118;border:1px solid var(--line);color:var(--text);
  border-radius:10px;padding:10px 12px;font:12px/1.4 var(--mono)}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{background:linear-gradient(135deg, var(--acc), var(--acc2));color:#06111f;border:none;
  border-radius:10px;padding:10px 14px;font:12px/1 var(--font);font-weight:800;cursor:pointer;
  box-shadow:0 10px 24px var(--glow)}
.btn.secondary{background:rgba(94,200,255,.14);color:var(--acc);box-shadow:none}
.btn:disabled{opacity:.6;cursor:not-allowed}
.subtle{font-size:11px;color:var(--muted)}
.job-block{margin-bottom:12px}
.live-row{display:grid;grid-template-columns:160px 1fr 80px 80px;gap:8px;align-items:center;padding:6px 0}
@media(max-width:700px){.live-row{grid-template-columns:1fr;gap:4px}}
.live-stage{font-size:12px}
.live-track{height:10px;background:rgba(36,53,72,.82);border-radius:5px;overflow:hidden}
.live-fill{height:100%;background:linear-gradient(90deg,var(--acc),var(--ok));width:100%}
.result-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
@media(max-width:900px){.result-metrics{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.result-metrics{grid-template-columns:1fr}}
.metric{padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1118}
.metric .k{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.metric .v{font-size:16px;font-weight:700;margin-top:4px}
.panel-grid{display:grid;grid-template-columns:1.25fr .95fr;gap:14px;margin-bottom:14px}
@media(max-width:1100px){.panel-grid{grid-template-columns:1fr}}
.pill-row{display:flex;flex-wrap:wrap;gap:8px}
.info-list{display:grid;gap:8px}
.info-item{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid rgba(36,53,72,.56)}
.info-item:last-child{border-bottom:none}
.info-item .label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.info-item .value{text-align:right;font-family:var(--mono);font-size:12px}
.path-cell{font-family:var(--mono);font-size:11px;word-break:break-all}
.kv-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
@media(max-width:700px){.kv-grid{grid-template-columns:1fr}}
.empty{color:var(--muted);font-size:12px}
.run-list{display:grid;gap:10px}
.run-item{padding:12px;border:1px solid var(--line);border-radius:12px;background:#0b1118}
.run-top{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
.run-name{font-weight:700}
.run-meta{font-size:11px;color:var(--muted);margin-top:6px;font-family:var(--mono)}
</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div class="brand">PJC <span>X-UI</span></div>
    <div class="brand-sub">Admin-only control center and audit center for PJC, SSE handoff, and release review.</div>
    <nav class="nav">
      <a href="#overview">Overview</a>
      <a href="#control">Control Center</a>
      <a href="#audit">Audit Center</a>
      <a href="#history">Run Analytics</a>
    </nav>
    <div class="side-note">Loopback-only local admin shell. Treat <code>POST /v1/jobs/start</code> as privileged because it can launch the pipeline and expose live run artifacts.</div>
  </aside>
  <div class="content">
    <header>
      <div>
        <div class="hero-title">PJC Control and Audit Center</div>
        <div class="hero-sub">Single admin shell for job launch, live SSE-backed progress, audit chain review, and release confirmation.</div>
        <div class="meta-row" id="meta-row">
          <div class="loading"><div class="spinner"></div>loading…</div>
        </div>
      </div>
      <div class="countdown" id="countdown"></div>
    </header>
    <div id="main"><div class="loading"><div class="spinner"></div>loading…</div></div>
  </div>
</div>

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
function shortText(s){ return esc(s || "—"); }
function boolWord(v){
  if(v===true) return "true";
  if(v===false) return "false";
  return "—";
}
function metricCard(label, value, subline){
  return `<div class="hero-card"><div class="hero-k">${esc(label)}</div><div class="hero-v">${value}</div><div class="hero-subline">${subline||""}</div></div>`;
}

function renderHeader(data){
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

function renderOverviewCards(data){
  const job = data.job_control || {};
  const audit = data.audit_center || {};
  const artifact = audit.artifact_inventory || {};
  const sse = audit.sse || {};
  const pipeline = audit.pipeline || {};
  const mainline = audit.mainline_contract || {};
  const recent = data.recent_runs || {};
  const cards = [
    metricCard("Platform Status", badge(data.overall_status), `${shortText(data.job_id)} / ${fmtTs(data.generated_at_utc)}`),
    metricCard("Current Control State", shortText(job.state || "idle"), `job ${shortText(job.job_id || "—")}`),
    metricCard("Artifact Coverage", shortText(`${artifact.available_count||0}/${artifact.total_count||0}`), `${shortText(audit.out_base_display || "—")} active artifacts`),
    metricCard("SSE Audit", shortText(`${sse.export_record_count||0} / ${sse.recovery_record_count||0}`), `export / recovery records, release=${boolWord(pipeline.released)}`),
    metricCard("Recent Runs", shortText(recent.returned_count ?? 0), `search root ${shortText(recent.search_dir_display || "—")}`),
  ];
  if(mainline.status){
    cards.push(metricCard("Mainline Contract", shortText(mainline.status), `handoff=${shortText(mainline.handoff_mode || "—")} cleanup s=${shortText((mainline.handoff_cleanup||{}).server || "—")} c=${shortText((mainline.handoff_cleanup||{}).client || "—")}`));
  }else{
    cards.push(metricCard("Mainline Contract", "—", "audit_chain.json not available yet"));
  }
  return `<section id="overview"><div class="hero-grid">${cards.join("")}</div></section>`;
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

let _lastDashboard = null;
let _jobPollTimer = null;
let _panelOverride = "";

function newJobId(){
  const d = new Date();
  const bits = [
    d.getUTCFullYear(),
    String(d.getUTCMonth()+1).padStart(2,"0"),
    String(d.getUTCDate()).padStart(2,"0"),
    String(d.getUTCHours()).padStart(2,"0"),
    String(d.getUTCMinutes()).padStart(2,"0"),
    String(d.getUTCSeconds()).padStart(2,"0")
  ];
  return `dashboard_job_${bits.join("")}`;
}

function renderJobSetup(job){
  const outBase = esc((job&&job.out_base) || "");
  return `<div class="card job-block"><h3>Control Center</h3>
    <div class="subtle" style="margin-bottom:10px">Admin launch path. This X-UI shell still reuses the frozen <code>query_workflow_request/v1</code> contract instead of inventing a second control plane.</div>
    <div class="job-form">
      <div class="field">
        <label for="request_file">Request File</label>
        <input id="request_file" value="docs/examples/query_request.json" spellcheck="false">
      </div>
      <div class="field">
        <label for="job_id_override">Job ID Override</label>
        <input id="job_id_override" value="${esc((job&&job.job_id)||newJobId())}" spellcheck="false">
      </div>
      <div class="field">
        <label for="out_base_override">Out Base Override</label>
        <input id="out_base_override" value="${outBase}" spellcheck="false" placeholder="/abs/path/or/repo-relative">
      </div>
      <div class="actions">
        <button class="btn" onclick="startJob()">▶ Start Job</button>
        <button class="btn secondary" onclick="prefillExample()">Use Example</button>
      </div>
    </div>
  </div>`;
}

function prefillExample(){
  const requestInput = document.getElementById("request_file");
  const jobInput = document.getElementById("job_id_override");
  if(requestInput) requestInput.value = "docs/examples/query_request.json";
  if(jobInput && !jobInput.value) jobInput.value = newJobId();
}

function renderLiveProgress(job){
  const stages = Array.isArray(job.stages) ? job.stages : [];
  const rows = stages.map((s)=>{
    const cls = statusClass(s.status);
    const fill = s.status === "waiting" ? "0%" : "100%";
    return `<div class="live-row">
      <div class="live-stage">${esc(s.name)}</div>
      <div class="live-track">${s.status==="waiting" ? "" : `<div class="live-fill" style="width:${fill};opacity:${cls==="err" ? ".6" : "1"}"></div>`}</div>
      <div>${badge(s.status)}</div>
      <div class="num">${ms(s.duration_ms)}</div>
    </div>`;
  }).join("");
  return `<div class="card job-block"><h3>Control Center</h3>
    <div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px">
      <span class="wf-state">${badge(job.state||"running")}</span>
      <span class="meta">job <b>${esc(job.job_id||"—")}</b></span>
      ${job.elapsed_sec!=null?`<span class="meta">elapsed <b>${esc(job.elapsed_sec)}s</b></span>`:""}
      ${job.exit_code!=null?`<span class="meta">exit <b>${esc(job.exit_code)}</b></span>`:""}
    </div>
    <div class="subtle" style="margin-bottom:10px">Live stage view for the current admin-controlled run. Historical analytics stay below to avoid mixing stale and active state.</div>
    ${rows || "<div class='subtle'>Waiting for stage artifacts…</div>"}
  </div>`;
}

function renderResultCard(job, audit){
  const result = job.result || {};
  const wrapper = (audit||{}).wrapper || {};
  const relaunchLabel = wrapper.relaunch_action === "retry" ? "Retry Job" : wrapper.relaunch_action === "resubmit" ? "Re-submit Job" : "";
  return `<div class="card job-block"><h3>Control Center</h3>
    <div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px">
      <span class="wf-state">${badge(job.state||"unknown")}</span>
      <span class="meta">job <b>${esc(job.job_id||"—")}</b></span>
      ${job.elapsed_sec!=null?`<span class="meta">elapsed <b>${esc(job.elapsed_sec)}s</b></span>`:""}
      ${job.exit_code!=null?`<span class="meta">exit <b>${esc(job.exit_code)}</b></span>`:""}
    </div>
    <div class="result-metrics">
      <div class="metric"><div class="k">Intersection Size</div><div class="v">${esc(result.intersection_size ?? "—")}</div></div>
      <div class="metric"><div class="k">Intersection Sum</div><div class="v">${esc(result.intersection_sum ?? "—")}</div></div>
      <div class="metric"><div class="k">Released</div><div class="v">${result.released===true ? "true" : result.released===false ? "false" : "—"}</div></div>
      <div class="metric"><div class="k">Reason Code</div><div class="v">${esc(result.reason_code || "—")}</div></div>
    </div>
    <div class="actions">
      <button class="btn secondary" onclick="showSetup()">Start New Job</button>
      ${wrapper.relaunch_supported ? `<button class="btn secondary" onclick="relaunchCurrentJob()">${esc(relaunchLabel)}</button>` : ""}
      ${result.out_base ? `<a class="btn secondary" href="/v1/jobs/${encodeURIComponent(job.job_id)}/result" target="_blank" rel="noreferrer">View JSON</a>` : ""}
    </div>
  </div>`;
}

function renderAuditOverview(audit){
  if(!audit) return "";
  const wrapper = audit.wrapper || {};
  const pipeline = audit.pipeline || {};
  const mainline = audit.mainline_contract || {};
  const relaunchLabel = wrapper.relaunch_action === "retry" ? "Retry" : wrapper.relaunch_action === "resubmit" ? "Re-submit" : "";
  return `<div class="card"><h3>Audit Center</h3>
    <div class="info-list">
      <div class="info-item"><span class="label">Out Base</span><span class="value">${shortText(audit.out_base_display || audit.out_base)}</span></div>
      <div class="info-item"><span class="label">Wrapper Receipts</span><span class="value">${shortText(wrapper.receipt_count ?? 0)} / latest=${shortText(wrapper.latest_event || "—")}</span></div>
      <div class="info-item"><span class="label">Recommended Action</span><span class="value">${shortText(wrapper.recommended_action || "—")}</span></div>
      <div class="info-item"><span class="label">Durable Wrapper</span><span class="value">${wrapper.relaunch_supported ? `${shortText(relaunchLabel)} via ${shortText(wrapper.request_file_display || "—")}` : shortText(wrapper.request_file_display || wrapper.request_source || "—")}</span></div>
      <div class="info-item"><span class="label">Release</span><span class="value">${boolWord(pipeline.released)} / ${shortText(pipeline.reason_code || "—")}</span></div>
      <div class="info-item"><span class="label">Mainline Contract</span><span class="value">${shortText(mainline.status || "—")} / handoff=${shortText(mainline.handoff_mode || "—")}</span></div>
      <div class="info-item"><span class="label">Service Audit Consistency</span><span class="value">server=${shortText((mainline.service_audit_consistency||{}).server || "—")} client=${shortText((mainline.service_audit_consistency||{}).client || "—")}</span></div>
    </div>
    ${wrapper.relaunch_supported ? `<div class="actions" style="margin-top:12px"><button class="btn secondary" onclick="relaunchCurrentJob()">${esc(relaunchLabel)} Current Run</button></div>` : ""}
  </div>`;
}

function renderSSEAudit(audit){
  if(!audit || !audit.sse) return "";
  const sse = audit.sse;
  const rows = (sse.roles || []).map((r)=>`
    <tr>
      <td>${esc(r.role)}</td>
      <td>${badge(r.export_decision || "unknown", r.export_decision || "—")}</td>
      <td>${badge(r.recovery_decision || "unknown", r.recovery_decision || "—")}</td>
      <td>${esc(r.boundary || "—")}</td>
      <td>${esc(r.transport || "—")}</td>
      <td>${esc(r.auth_mode || "—")}</td>
      <td class="num">${esc(r.output_rows ?? "—")}</td>
      <td class="num">${ms(r.duration_ms)}</td>
      <td>${esc(r.output_file_type || "—")}</td>
    </tr>`).join("");
  return `<div class="card"><h3>SSE Audit</h3>
    <div class="subtle" style="margin-bottom:10px">Integrated SSE export and record-recovery audit for admin review. This is the primary live view for transport, auth, and handoff boundary state.</div>
    <div class="pill-row" style="margin-bottom:10px">
      ${badge("ok", `export ${sse.export_record_count||0}`)}
      ${badge("ok", `recovery ${sse.recovery_record_count||0}`)}
      ${badge("unknown", `roles ${(sse.roles||[]).length}`)}
    </div>
    <table><thead><tr><th>Role</th><th>Export</th><th>Recovery</th><th>Boundary</th><th>Transport</th><th>Auth</th><th>Rows</th><th>Dur</th><th>Output</th></tr></thead>
    <tbody>${rows || "<tr><td colspan='9' class='empty'>No SSE audit records yet</td></tr>"}</tbody></table>
  </div>`;
}

function renderArtifactInventory(audit){
  if(!audit || !audit.artifact_inventory) return "";
  const inv = audit.artifact_inventory;
  const rows = (inv.items || []).map((item)=>`
    <tr>
      <td>${esc(item.label)}</td>
      <td>${badge(item.available ? "ok" : "unknown", item.available ? "present" : "missing")}</td>
      <td class="path-cell">${esc(item.display_path || item.path || "—")}</td>
    </tr>`).join("");
  return `<div class="card"><h3>Artifact Inventory</h3>
    <div class="subtle" style="margin-bottom:10px">Admin audit surface over wrapper sidecars, SSE logs, bridge/PJC artifacts, and audit-chain outputs.</div>
    <table><thead><tr><th>Artifact</th><th>Status</th><th>Path</th></tr></thead>
    <tbody>${rows || "<tr><td colspan='3' class='empty'>No tracked artifacts</td></tr>"}</tbody></table>
  </div>`;
}

function renderRecentRuns(recentRuns, activeOutBase, job){
  if(!recentRuns) return "";
  const statuses = Array.isArray(recentRuns.statuses) ? recentRuns.statuses : [];
  const rows = statuses.map((item)=>{
    const isActive = item.out_base === activeOutBase;
    const switchBlocked = !!(job && job.state === "running" && job.out_base && job.out_base !== item.out_base);
    const encodedOutBase = encodeURIComponent(item.out_base || "");
    return `<div class="run-item">
      <div class="run-top">
        <div>
          <div class="run-name">${esc(item.job_id || "unknown_job")} ${isActive ? badge("ok","active") : ""}</div>
          <div class="run-meta">${esc(item.out_base_display || item.out_base || "—")}</div>
        </div>
        <div class="actions">
          ${badge(item.state || "unknown")}
          <button class="btn secondary" onclick="openRun(decodeURIComponent('${encodedOutBase}'))" ${switchBlocked ? "disabled" : ""}>Open</button>
        </div>
      </div>
      <div class="run-meta">updated=${fmtTs(item.last_updated_at_utc)} caller=${esc(item.caller || "—")} tenant=${esc(item.tenant_id || "—")} receipts=${esc(item.receipt_count ?? "—")}</div>
    </div>`;
  }).join("");
  return `<div class="card"><h3>Recent Runs</h3>
    <div class="subtle" style="margin-bottom:10px">Switch the active control/audit view without restarting the shell. Selection is blocked while another job is actively running.</div>
    <div class="subtle" style="margin-bottom:10px">search root: <span class="mono">${esc(recentRuns.search_dir_display || recentRuns.search_dir || "—")}</span></div>
    <div class="run-list">${rows || "<div class='empty'>No prior runs found under the history root.</div>"}</div>
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
  _lastDashboard = data;
  const d = data.dashboard||{};
  const panels = d.panels||{};
  const alerts = data.alerts||null;
  const health = data.health||null;
  const job = data.job_control||null;
  const recentRuns = data.recent_runs||null;
  const activeOutBase = (data.audit_center||{}).out_base || (job&&job.out_base) || "";
  const panelState = _panelOverride || (job&&job.state ? job.state : "idle");
  const showHistory = panelState !== "running";
  renderHeader(data);
  const blocks = [renderOverviewCards(data)];
  blocks.push(`<section id="control" class="panel-grid">${
    panelState === "running" && job
      ? renderLiveProgress(job)
      : (panelState === "completed" || panelState === "failed") && job
      ? renderResultCard(job, data.audit_center||null)
      : renderJobSetup(job)
  }${renderAuditOverview(data.audit_center||null)}</section>`);
  blocks.push(`<section id="audit" class="grid g2">${renderSSEAudit(data.audit_center||null)}${renderArtifactInventory(data.audit_center||null)}</section>`);
  blocks.push(`<section class="grid g2">${renderRecentRuns(recentRuns, activeOutBase, job)}</section>`);
  blocks.push(`<div class="grid g2">${renderAlerts(alerts)}${renderHealth(health)}</div>`);
  const historyBlocks = [];
  if(showHistory){
    historyBlocks.push(
      `<div class="grid g3">` +
      renderStageSummary(panels) +
      renderStageDuration(panels) +
      renderReleaseOutcomes(panels) +
      `</div>`
    );
    historyBlocks.push(
      `<div class="grid g2">` +
      renderFailureSummary(panels) +
      renderStageTimeline(panels) +
      `</div>`
    );
  }
  blocks.push(`<section id="history"><div class="section-title">Run Analytics</div>${historyBlocks.join("") || `<div class="card"><div class="empty">Historical analytics are hidden while a live run is active.</div></div>`}</section>`);
  document.getElementById("main").innerHTML = blocks.filter(Boolean).join("\n");
  if(job && job.job_id && job.state === "running"){
    ensureJobPolling(job.job_id);
  }else{
    stopJobPolling();
  }
}

function stopJobPolling(){
  if(_jobPollTimer){
    clearTimeout(_jobPollTimer);
    _jobPollTimer = null;
  }
}

async function fetchJob(jobId){
  try{
    const resp = await fetch(`/v1/jobs/${encodeURIComponent(jobId)}`, {cache:"no-store"});
    const data = await resp.json();
    if(!resp.ok){
      stopJobPolling();
      return;
    }
    if(_lastDashboard){
      _lastDashboard.job_control = data;
      render(_lastDashboard);
    }
    if(data.state === "running"){
      _jobPollTimer = setTimeout(()=>fetchJob(jobId), 2000);
    }else{
      stopJobPolling();
      _panelOverride = "";
      load();
    }
  }catch(_e){
    stopJobPolling();
  }
}

function ensureJobPolling(jobId){
  if(_jobPollTimer) return;
  _jobPollTimer = setTimeout(()=>fetchJob(jobId), 2000);
}

function showSetup(){
  _panelOverride = "idle";
  if(_lastDashboard) render(_lastDashboard);
}

async function startJob(){
  const requestFile = document.getElementById("request_file")?.value?.trim();
  const jobId = document.getElementById("job_id_override")?.value?.trim();
  const outBase = document.getElementById("out_base_override")?.value?.trim();
  const body = {
    request_file: requestFile,
    overrides: {
      job_id: jobId || undefined,
      out_base: outBase || undefined
    }
  };
  try{
    const resp = await fetch("/v1/jobs/start", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if(!resp.ok){
      document.getElementById("main").innerHTML =
        `<div class="error-msg">Could not start job: ${esc(data.message || data.error || JSON.stringify(data))}</div>`;
      return;
    }
    _panelOverride = "";
    stopJobPolling();
    await load();
  }catch(e){
    document.getElementById("main").innerHTML =
      `<div class="error-msg">Could not start job: ${esc(String(e))}</div>`;
  }
}

async function openRun(outBase){
  try{
    const resp = await fetch("/v1/runs/select", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({out_base: outBase})
    });
    const data = await resp.json();
    if(!resp.ok){
      document.getElementById("main").innerHTML =
        `<div class="error-msg">Could not switch run: ${esc(data.message || data.error || JSON.stringify(data))}</div>`;
      return;
    }
    _panelOverride = "";
    stopJobPolling();
    await load();
  }catch(e){
    document.getElementById("main").innerHTML =
      `<div class="error-msg">Could not switch run: ${esc(String(e))}</div>`;
  }
}

async function relaunchCurrentJob(){
  const job = (_lastDashboard && _lastDashboard.job_control) || null;
  const wrapper = ((_lastDashboard && _lastDashboard.audit_center) || {}).wrapper || {};
  if(!job || !job.job_id){
    document.getElementById("main").innerHTML =
      `<div class="error-msg">Could not relaunch job: no active job selected</div>`;
    return;
  }
  try{
    const resp = await fetch(`/v1/jobs/${encodeURIComponent(job.job_id)}/relaunch`, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        action: wrapper.relaunch_action || undefined,
        overrides: {
          job_id: wrapper.suggested_job_id || undefined,
          out_base: wrapper.suggested_out_base || undefined,
        }
      })
    });
    const data = await resp.json();
    if(!resp.ok){
      document.getElementById("main").innerHTML =
        `<div class="error-msg">Could not relaunch job: ${esc(data.message || data.error || JSON.stringify(data))}</div>`;
      return;
    }
    _panelOverride = "";
    stopJobPolling();
    await load();
  }catch(e){
    document.getElementById("main").innerHTML =
      `<div class="error-msg">Could not relaunch job: ${esc(String(e))}</div>`;
  }
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
  document.getElementById("countdown").textContent=`refresh in ${_countdown}s`;
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


def invalidate_dashboard_cache() -> None:
    global _cache_data, _cache_ts
    with _cache_lock:
        _cache_data = None
        _cache_ts = 0.0


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _repo_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = base_dir if base_dir is not None else REPO_ROOT
    return (root / path).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_to_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _extract_result_summary(out_base: Path) -> dict[str, Any] | None:
    report = _load_optional(out_base / "a_psi_run" / "public_report.json")
    result = _load_optional(out_base / "a_psi_run" / "attribution_result.json")
    if report is None and result is None:
        return None
    details = report.get("details") if isinstance(report, dict) and isinstance(report.get("details"), dict) else {}
    intersection_size = _first_nonempty(
        details.get("intersection_size"),
        result.get("intersection_size") if isinstance(result, dict) else None,
    )
    intersection_sum = _first_nonempty(
        details.get("intersection_sum_raw"),
        details.get("intersection_sum"),
        result.get("intersection_sum") if isinstance(result, dict) else None,
    )
    return {
        "intersection_size": int(intersection_size) if isinstance(intersection_size, int) else intersection_size,
        "intersection_sum": int(intersection_sum) if isinstance(intersection_sum, int) else intersection_sum,
        "released": report.get("released") if isinstance(report, dict) else None,
        "reason_code": _first_nonempty(
            report.get("reason_code") if isinstance(report, dict) else None,
            details.get("reason_code") if isinstance(details, dict) else None,
        ),
        "out_base": str(out_base),
    }


def _dict_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _latest_records_by_role(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        role = str(record.get("role") or "unknown")
        prev = latest.get(role)
        if prev is None or str(record.get("ts_utc") or "") >= str(prev.get("ts_utc") or ""):
            latest[role] = record
    return latest


def _display_path(path: Path, *, out_base: Path) -> str:
    resolved = path.expanduser().resolve()
    if resolved == out_base:
        return out_base.name or str(out_base)
    for base in (out_base, REPO_ROOT):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return str(resolved)


def _artifact_entry(out_base: Path, relative_path: str, *, label: str) -> dict[str, Any]:
    path = out_base / relative_path
    return {
        "label": label,
        "path": str(path),
        "display_path": _display_path(path, out_base=out_base),
        "available": path.is_file(),
    }


def _utc_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _suggested_job_id(job_id: str | None, *, action: str) -> str:
    base = str(job_id or "dashboard_job").strip() or "dashboard_job"
    return f"{base}_{action}_{_utc_suffix()}"


def _suggested_out_base(out_base: Path, *, suggested_job_id: str) -> Path:
    return (out_base.parent / suggested_job_id).resolve()


def _build_relaunch_context(
    out_base: Path,
    *,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    recommended_action = workflow_status.get("recommended_action") if workflow_status else None
    relaunch_action = recommended_action if recommended_action in {"retry", "resubmit"} else None
    request_file = manifest.get("request_file") if isinstance(manifest, dict) else None
    request_path: Path | None = None
    request_file_exists = False
    if isinstance(request_file, str) and request_file and request_file != "<inline>":
        request_path = _repo_path(request_file)
        request_file_exists = request_path.is_file()
    job_id = workflow_status_raw.get("job_id") if workflow_status_raw else None
    suggested_job_id = _suggested_job_id(str(job_id) if job_id else None, action=relaunch_action or "rerun")
    suggested_out_base = _suggested_out_base(out_base, suggested_job_id=suggested_job_id)
    return {
        "relaunch_action": relaunch_action,
        "relaunch_supported": bool(relaunch_action and request_file_exists),
        "request_file": request_file,
        "request_file_exists": request_file_exists,
        "request_file_display": _display_path(request_path, out_base=out_base) if request_path is not None else request_file,
        "suggested_job_id": suggested_job_id,
        "suggested_out_base": str(suggested_out_base),
        "suggested_out_base_display": _display_path(suggested_out_base, out_base=out_base),
    }


def _build_audit_center(
    out_base: Path,
    *,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
) -> dict[str, Any]:
    audit_chain_path = out_base / "audit_chain.json"
    audit_chain = _load_optional(audit_chain_path)
    manifest = _load_optional(out_base / "query_workflow" / "submission_manifest.json")
    receipts = _load_jsonl_objects(out_base / "query_workflow" / "execution_receipts.jsonl")

    if audit_chain is not None:
        sse_export_records = _dict_records(audit_chain.get("sse_export_audit"))
        recovery_records = _dict_records(audit_chain.get("record_recovery_service_audit"))
        bridge_records = _dict_records(audit_chain.get("bridge_audit"))
        pjc_records = _dict_records(audit_chain.get("pjc_audit"))
        policy_records = _dict_records(audit_chain.get("policy_audit"))
    else:
        sse_export_records = _load_jsonl_objects(out_base / "sse_exports" / "export_audit.jsonl")
        recovery_records = _load_jsonl_objects(out_base / "sse_exports" / "record_recovery_service_audit.jsonl")
        bridge_records = _load_jsonl_objects(out_base / "bridge_job" / "bridge_audit.jsonl")
        pjc_records = _load_jsonl_objects(out_base / "a_psi_run" / "pjc_audit.jsonl")
        policy_records = _load_jsonl_objects(out_base / "a_psi_run" / "audit_log.jsonl")

    export_by_role = _latest_records_by_role(sse_export_records)
    recovery_by_role = _latest_records_by_role(recovery_records)
    roles = sorted(set(export_by_role) | set(recovery_by_role) | {"server", "client"})
    sse_roles: list[dict[str, Any]] = []
    for role_name in roles:
        export_record = export_by_role.get(role_name, {})
        recovery_record = recovery_by_role.get(role_name, {})
        sse_roles.append({
            "role": role_name,
            "boundary": export_record.get("record_recovery_boundary"),
            "export_decision": export_record.get("decision"),
            "export_reason_code": export_record.get("reason_code"),
            "recovery_decision": recovery_record.get("decision"),
            "recovery_reason_code": recovery_record.get("reason_code"),
            "transport": recovery_record.get("transport"),
            "auth_mode": recovery_record.get("auth_mode"),
            "output_rows": _first_nonempty(recovery_record.get("output_rows"), export_record.get("output_rows")),
            "duration_ms": _first_nonempty(recovery_record.get("duration_ms"), export_record.get("duration_ms")),
            "output_file_type": _first_nonempty(recovery_record.get("output_file_type"), export_record.get("output_file_type")),
        })

    mainline_summary = summarize_mainline_contract(audit_chain) if audit_chain is not None else None
    public_report = _load_optional(out_base / "a_psi_run" / "public_report.json")
    result = _extract_result_summary(out_base) or {}
    latest_receipt = receipts[-1] if receipts else {}
    relaunch_context = _build_relaunch_context(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
        manifest=manifest,
    )
    artifact_items = [
        _artifact_entry(out_base, "query_workflow/submission_manifest.json", label="Submission Manifest"),
        _artifact_entry(out_base, "query_workflow/execution_receipts.jsonl", label="Execution Receipts"),
        _artifact_entry(out_base, "query_workflow/status.json", label="Workflow Status"),
        _artifact_entry(out_base, "sse_exports/export_audit.jsonl", label="SSE Export Audit"),
        _artifact_entry(out_base, "sse_exports/record_recovery_service_audit.jsonl", label="SSE Recovery Service Audit"),
        _artifact_entry(out_base, "sse_exports/record_recovery_service_health.json", label="SSE Recovery Service Health"),
        _artifact_entry(out_base, "bridge_job/job_meta.json", label="Bridge Job Meta"),
        _artifact_entry(out_base, "bridge_job/bridge_audit.jsonl", label="Bridge Audit"),
        _artifact_entry(out_base, "a_psi_run/pjc_audit.jsonl", label="PJC Audit"),
        _artifact_entry(out_base, "a_psi_run/attribution_result.json", label="PJC Result"),
        _artifact_entry(out_base, "a_psi_run/public_report.json", label="Public Report"),
        _artifact_entry(out_base, "a_psi_run/audit_log.jsonl", label="Policy Release Audit"),
        _artifact_entry(out_base, "audit_chain.json", label="Audit Chain"),
        _artifact_entry(out_base, "audit_chain.seal.json", label="Audit Chain Seal"),
        _artifact_entry(out_base, "mainline_contract_check.json", label="Mainline Contract Check"),
        _artifact_entry(out_base, "platform_health.json", label="Platform Health Snapshot"),
        _artifact_entry(out_base, "pipeline_observability.json", label="Pipeline Observability"),
    ]
    available_count = sum(1 for item in artifact_items if item["available"])

    return {
        "out_base": str(out_base),
        "out_base_display": _display_path(out_base, out_base=out_base),
        "artifact_inventory": {
            "total_count": len(artifact_items),
            "available_count": available_count,
            "items": artifact_items,
        },
        "wrapper": {
            "state": workflow_status_raw.get("state") if workflow_status_raw else None,
            "recommended_action": workflow_status.get("recommended_action") if workflow_status else None,
            "receipt_count": len(receipts),
            "latest_event": latest_receipt.get("event"),
            "latest_error_class": latest_receipt.get("error_class"),
            "request_source": manifest.get("request_file") if isinstance(manifest, dict) else None,
            **relaunch_context,
        },
        "sse": {
            "export_record_count": len(sse_export_records),
            "recovery_record_count": len(recovery_records),
            "roles": sse_roles,
        },
        "pipeline": {
            "bridge_record_count": len(bridge_records),
            "pjc_record_count": len(pjc_records),
            "policy_record_count": len(policy_records),
            "released": result.get("released"),
            "reason_code": result.get("reason_code") or (public_report or {}).get("reason_code"),
            "intersection_size": result.get("intersection_size"),
            "intersection_sum": result.get("intersection_sum"),
        },
        "audit_chain": {
            "available": audit_chain is not None,
            "counts": audit_chain.get("counts") if isinstance(audit_chain, dict) else None,
        },
        "mainline_contract": mainline_summary,
    }


def _build_recent_runs(search_dir: Path, *, active_out_base: Path, limit: int) -> dict[str, Any]:
    statuses, total = scan_status_files(search_dir, limit=limit)
    for item in statuses:
        item["out_base_display"] = _display_path(Path(str(item.get("out_base") or "")), out_base=active_out_base)
        item["active"] = str(item.get("out_base") or "") == str(active_out_base)
    return {
        "search_dir": str(search_dir),
        "search_dir_display": _display_path(search_dir, out_base=active_out_base),
        "total_found": total,
        "returned_count": len(statuses),
        "limit": limit,
        "statuses": statuses,
    }


def _stage_rows_from_observability(observability: dict[str, Any], *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    events = observability.get("events")
    if not isinstance(events, list):
        return []
    latest_by_stage: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        stage = event.get("stage")
        if not isinstance(stage, str) or not stage:
            continue
        prev = latest_by_stage.get(stage)
        if prev is None or str(event.get("ts_utc") or "") >= str(prev.get("ts_utc") or ""):
            latest_by_stage[stage] = event
    order = ["sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"]
    rows: list[dict[str, Any]] = []
    for stage in order:
        event = latest_by_stage.get(stage)
        if event is None:
            status = "error" if terminal_state == "failed" and not rows else "waiting"
            rows.append({"name": stage, "status": status, "duration_ms": None})
            continue
        status = str(event.get("status") or "unknown")
        if terminal_state == "running" and stage == order[-1] and status == "unknown":
            status = "running"
        if terminal_state == "failed" and exit_code not in (None, 0) and status == "unknown":
            status = "error"
        rows.append({
            "name": stage,
            "status": status,
            "duration_ms": event.get("duration_ms"),
        })
    return rows


def _stage_rows_from_files(out_base: Path, *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    rows = [
        {"name": "sse_export", "status": "waiting", "duration_ms": None},
        {"name": "record_recovery_service", "status": "waiting", "duration_ms": None},
        {"name": "bridge", "status": "waiting", "duration_ms": None},
        {"name": "pjc", "status": "waiting", "duration_ms": None},
        {"name": "policy_release", "status": "waiting", "duration_ms": None},
    ]
    sse_dir = out_base / "sse_exports"
    bridge_dir = out_base / "bridge_job"
    a_psi_dir = out_base / "a_psi_run"
    public_report = _load_optional(a_psi_dir / "public_report.json")

    has_sse = (sse_dir / "export_audit.jsonl").is_file() or (sse_dir / "server.csv").exists() or (sse_dir / "server.fifo").exists()
    has_recovery = (sse_dir / "record_recovery_service_audit.jsonl").is_file() or (sse_dir / "record_recovery_service_health.json").is_file()
    has_bridge = (bridge_dir / "job_meta.json").is_file() or (bridge_dir / "bridge_audit.jsonl").is_file()
    has_pjc_result = (a_psi_dir / "attribution_result.json").is_file()
    has_pjc_audit = (a_psi_dir / "pjc_audit.jsonl").is_file()

    if has_sse:
        rows[0]["status"] = "ok"
    if has_recovery:
        rows[1]["status"] = "ok"
    elif has_bridge:
        rows[1]["status"] = "ok"
    if has_bridge:
        rows[2]["status"] = "ok"
    if has_pjc_result:
        rows[3]["status"] = "ok" if terminal_state != "running" else "running"
    elif has_pjc_audit:
        rows[3]["status"] = "running" if terminal_state == "running" else "ok"
    elif has_bridge and terminal_state == "running":
        rows[3]["status"] = "running"
    if public_report is not None:
        released = public_report.get("released")
        rows[4]["status"] = "ok" if released is True else "error" if released is False else "unknown"

    if terminal_state == "running":
        for row in rows:
            if row["status"] == "waiting":
                row["status"] = "running"
                break
    elif terminal_state == "failed" and exit_code not in (None, 0):
        for row in rows:
            if row["status"] == "waiting":
                row["status"] = "error"
                break
    return rows


def _derive_stage_rows(out_base: Path, *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    observability = _load_optional(out_base / "pipeline_observability.json")
    if observability is not None:
        rows = _stage_rows_from_observability(observability, terminal_state=terminal_state, exit_code=exit_code)
        if rows:
            return rows
    return _stage_rows_from_files(out_base, terminal_state=terminal_state, exit_code=exit_code)


def _job_elapsed_seconds(job: dict[str, Any]) -> float | None:
    start_ts = _iso_to_ts(job.get("started_at_utc"))
    if start_ts is None:
        return None
    if job.get("state") == "running":
        return round(max(0.0, time.time() - start_ts), 3)
    end_ts = _iso_to_ts(job.get("finished_at_utc")) or _iso_to_ts(job.get("last_updated_at_utc"))
    if end_ts is None:
        return None
    return round(max(0.0, end_ts - start_ts), 3)


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    out_base = Path(job["out_base"])
    snapshot = {
        "job_id": job.get("job_id"),
        "state": job.get("state"),
        "terminal": job.get("terminal"),
        "started_at_utc": job.get("started_at_utc"),
        "finished_at_utc": job.get("finished_at_utc"),
        "last_updated_at_utc": job.get("last_updated_at_utc"),
        "elapsed_sec": _job_elapsed_seconds(job),
        "exit_code": job.get("last_exit_code"),
        "out_base": str(out_base),
        "stages": _derive_stage_rows(out_base, terminal_state=str(job.get("state") or "unknown"), exit_code=job.get("last_exit_code")),
    }
    result = _extract_result_summary(out_base)
    if result is not None:
        snapshot["result"] = result
    return snapshot


def _seed_job_from_out_base(out_base: Path) -> dict[str, Any] | None:
    status_path = out_base / "query_workflow" / "status.json"
    status = _load_optional(status_path)
    if not status or status.get("schema") != QUERY_WORKFLOW_STATUS_SCHEMA:
        return None
    state = status.get("state") or "unknown"
    return {
        "job_id": status.get("job_id"),
        "state": state,
        "terminal": bool(status.get("terminal")),
        "started_at_utc": None,
        "finished_at_utc": status.get("last_updated_at_utc") if status.get("terminal") else None,
        "last_updated_at_utc": status.get("last_updated_at_utc"),
        "last_exit_code": status.get("last_exit_code"),
        "out_base": str(out_base),
        "request_source": None,
    }


def _build_data(out_base: Path, *, history_root: Path, history_limit: int) -> dict[str, Any]:
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

    audit_center = _build_audit_center(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
    )
    recent_runs = _build_recent_runs(history_root, active_out_base=out_base, limit=history_limit)

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
        "audit_center": audit_center,
        "recent_runs": recent_runs,
    }


def get_dashboard_data(out_base: Path, *, history_root: Path, history_limit: int) -> dict[str, Any]:
    global _cache_data, _cache_ts
    with _cache_lock:
        now = time.monotonic()
        if _cache_data is None or now - _cache_ts > CACHE_TTL:
            _cache_data = _build_data(out_base, history_root=history_root, history_limit=history_limit)
            _cache_ts = now
        return _cache_data


def _load_start_request(body: dict[str, Any], *, default_out_base: Path) -> tuple[dict[str, Any], str, Path]:
    overrides = body.get("overrides")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object when provided")

    if body.get("request_file"):
        request_file = body.get("request_file")
        if not isinstance(request_file, str) or not request_file.strip():
            raise ValueError("request_file must be a non-empty string")
        request_path = _repo_path(request_file)
        if not request_path.is_file():
            raise FileNotFoundError(f"request_file does not exist: {request_path}")
        raw_payload = load_request(request_path)
        request_source = str(request_path)
        request_dir = request_path.parent
    else:
        request_obj = body.get("request")
        if request_obj is None:
            request_obj = {k: v for k, v in body.items() if k not in {"overrides", "request_base_dir"}}
        if not isinstance(request_obj, dict):
            raise ValueError("request must be a JSON object")
        raw_payload = dict(request_obj)
        request_base_dir = body.get("request_base_dir")
        if request_base_dir is not None and (not isinstance(request_base_dir, str) or not request_base_dir.strip()):
            raise ValueError("request_base_dir must be a non-empty string when provided")
        request_dir = _repo_path(request_base_dir, base_dir=REPO_ROOT) if isinstance(request_base_dir, str) and request_base_dir else REPO_ROOT
        request_source = "<inline>"

    payload = dict(raw_payload)
    for field in ("job_id", "out_base"):
        if field in body and body[field] not in (None, ""):
            overrides[field] = body[field]
    if "out_base" not in overrides and not payload.get("out_base"):
        overrides["out_base"] = str(default_out_base)
    for key, value in overrides.items():
        if value not in (None, ""):
            if key == "out_base" and isinstance(value, str):
                payload[key] = str(_repo_path(value, base_dir=REPO_ROOT))
            else:
                payload[key] = value
    return payload, request_source, request_dir


def _load_relaunch_request(
    body: dict[str, Any],
    *,
    out_base: Path,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    manifest = _load_optional(out_base / "query_workflow" / "submission_manifest.json")
    relaunch_context = _build_relaunch_context(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
        manifest=manifest,
    )
    request_file = relaunch_context.get("request_file")
    if not relaunch_context.get("relaunch_supported") or not isinstance(request_file, str):
        raise ValueError("automatic relaunch is not supported for this run")
    requested_action = body.get("action")
    if requested_action not in (None, "", relaunch_context.get("relaunch_action")):
        raise ValueError(
            f"requested action {requested_action!r} does not match recommended action {relaunch_context.get('relaunch_action')!r}"
        )
    overrides = body.get("overrides")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object when provided")
    if not overrides.get("job_id"):
        overrides["job_id"] = relaunch_context.get("suggested_job_id")
    if not overrides.get("out_base"):
        overrides["out_base"] = relaunch_context.get("suggested_out_base")
    payload, request_source, request_dir = _load_start_request(
        {"request_file": request_file, "overrides": overrides},
        default_out_base=Path(str(overrides["out_base"])),
    )
    return payload, request_source, request_dir, relaunch_context


def _start_job_thread(server: "DashboardServer", *, payload: dict[str, Any], request_source: str, request_dir: Path) -> None:
    normalized = normalize_request_paths(payload, request_dir=request_dir)
    validate_request(normalized)
    command = build_command(normalized)
    request_digest = json_sha256(normalized)
    out_base = Path(str(normalized["out_base"])).resolve()
    sidecar_paths = query_workflow_sidecar_paths(str(out_base))
    manifest = render_manifest(
        request_source=request_source,
        payload=normalized,
        command=command,
        mode="execute",
        exit_code=None,
    )
    write_json(sidecar_paths["submission_manifest"], manifest)
    started_receipt = build_receipt(
        payload=normalized,
        mode="execute",
        event="started",
        request_digest=request_digest,
        command=command,
        exit_code=None,
    )
    append_jsonl(sidecar_paths["execution_receipts"], started_receipt)
    started_status = build_status(
        payload=normalized,
        mode="execute",
        state="running",
        terminal=False,
        latest_receipt=started_receipt,
        receipt_count=1,
        exit_code=None,
    )
    write_json(sidecar_paths["status"], started_status)

    job_record = {
        "job_id": normalized.get("job_id"),
        "state": "running",
        "terminal": False,
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "last_updated_at_utc": _utc_now(),
        "last_exit_code": None,
        "out_base": str(out_base),
        "request_source": request_source,
    }
    server.out_base = out_base
    server.set_job(job_record)

    def _runner() -> None:
        exit_code: int | None = None
        try:
            result = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
            exit_code = result.returncode
        except OSError:
            exit_code = 127

        finished_at = _utc_now()
        final_manifest = render_manifest(
            request_source=request_source,
            payload=normalized,
            command=command,
            mode="execute",
            exit_code=exit_code,
        )
        write_json(sidecar_paths["submission_manifest"], final_manifest)
        final_receipt = build_receipt(
            payload=normalized,
            mode="execute",
            event="completed" if exit_code in (None, 0) else "failed",
            request_digest=request_digest,
            command=command,
            exit_code=exit_code,
        )
        append_jsonl(sidecar_paths["execution_receipts"], final_receipt)
        final_status = build_status(
            payload=normalized,
            mode="execute",
            state="completed" if exit_code in (None, 0) else "failed",
            terminal=True,
            latest_receipt=final_receipt,
            receipt_count=2,
            exit_code=exit_code,
        )
        write_json(sidecar_paths["status"], final_status)
        server.set_job({
            "job_id": normalized.get("job_id"),
            "state": "completed" if exit_code in (None, 0) else "failed",
            "terminal": True,
            "started_at_utc": job_record["started_at_utc"],
            "finished_at_utc": finished_at,
            "last_updated_at_utc": finished_at,
            "last_exit_code": exit_code,
            "out_base": str(out_base),
            "request_source": request_source,
        })

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        out_base: Path,
        history_root: Path,
        history_limit: int,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.out_base = out_base
        self.history_root = history_root
        self.history_limit = history_limit
        self.pid_file = pid_file
        self.ready_file = ready_file
        self.job_lock = threading.Lock()
        self.current_job: dict[str, Any] | None = _seed_job_from_out_base(out_base)
        super().__init__(server_address, handler_cls)

    def get_job(self) -> dict[str, Any] | None:
        with self.job_lock:
            if self.current_job is None:
                return None
            return dict(self.current_job)

    def set_job(self, job: dict[str, Any] | None) -> None:
        with self.job_lock:
            self.current_job = dict(job) if job is not None else None
        invalidate_dashboard_cache()

    def recent_runs(
        self,
        *,
        filter_state: str | None = None,
        filter_job_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        use_limit = max(1, limit or self.history_limit)
        statuses, total = scan_status_files(
            self.history_root,
            filter_state=filter_state,
            filter_job_id=filter_job_id,
            limit=use_limit,
        )
        for item in statuses:
            item["out_base_display"] = _display_path(Path(str(item.get("out_base") or "")), out_base=self.out_base)
            item["active"] = str(item.get("out_base") or "") == str(self.out_base)
        return {
            "schema": "query_workflow_status_list/v1",
            "search_dir": str(self.history_root),
            "search_dir_display": _display_path(self.history_root, out_base=self.out_base),
            "filter_state": filter_state,
            "filter_job_id": filter_job_id,
            "total_found": total,
            "returned_count": len(statuses),
            "limit": use_limit,
            "statuses": statuses,
        }

    def select_out_base(self, out_base: Path) -> dict[str, Any] | None:
        resolved = out_base.expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"out_base does not exist: {resolved}")
        try:
            resolved.relative_to(self.history_root)
        except ValueError as exc:
            raise ValueError(f"out_base must stay under history_root: {self.history_root}") from exc
        current = self.get_job()
        if current is not None and current.get("state") == "running" and str(current.get("out_base") or "") != str(resolved):
            raise RuntimeError("cannot switch active run while another job is running")
        self.out_base = resolved
        self.set_job(_seed_job_from_out_base(resolved))
        return self.get_job()


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

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _current_job_snapshot(self) -> dict[str, Any] | None:
        job = self.server.get_job()
        if job is None:
            return None
        return _job_snapshot(job)

    def _job_snapshot_or_404(self, job_id: str) -> dict[str, Any] | None:
        job = self.server.get_job()
        if job is None or str(job.get("job_id") or "") != job_id:
            return None
        return _job_snapshot(job)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if path in ("/", "/index.html"):
            body = _DASHBOARD_HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif path == "/healthz":
            self._send_json(200, {"status": "ok", "schema": "operator_dashboard_health/v1"})
        elif path == "/v1/dashboard":
            data = get_dashboard_data(
                self.server.out_base,
                history_root=self.server.history_root,
                history_limit=self.server.history_limit,
            )
            data = dict(data)
            data["job_control"] = self._current_job_snapshot()
            self._send_json(200, data)
        elif path == "/v1/runs":
            limit_raw = query.get("limit", [""])[0]
            state = query.get("state", [""])[0] or None
            job_id = query.get("job_id", [""])[0] or None
            limit = self.server.history_limit
            if limit_raw:
                try:
                    limit = max(1, int(limit_raw))
                except ValueError:
                    self._send_json(400, {"error": "invalid_limit", "message": f"invalid limit: {limit_raw}"})
                    return
            self._send_json(200, self.server.recent_runs(filter_state=state, filter_job_id=job_id, limit=limit))
        elif path.startswith("/v1/jobs/") and path.endswith("/result"):
            job_id = unquote(path[len("/v1/jobs/") : -len("/result")]).strip("/")
            snapshot = self._job_snapshot_or_404(job_id)
            if snapshot is None:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            if snapshot.get("state") not in {"completed", "failed"}:
                self._send_json(404, {"error": "result_not_ready", "job_id": job_id})
                return
            result = snapshot.get("result") or {}
            self._send_json(200, {
                "job_id": snapshot.get("job_id"),
                "state": snapshot.get("state"),
                "elapsed_sec": snapshot.get("elapsed_sec"),
                "exit_code": snapshot.get("exit_code"),
                "intersection_size": result.get("intersection_size"),
                "intersection_sum": result.get("intersection_sum"),
                "released": result.get("released"),
                "reason_code": result.get("reason_code"),
                "out_base": snapshot.get("out_base"),
            })
        elif path.startswith("/v1/jobs/"):
            job_id = unquote(path[len("/v1/jobs/") :]).strip("/")
            snapshot = self._job_snapshot_or_404(job_id)
            if snapshot is None:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            self._send_json(200, snapshot)
        else:
            self._send_json(404, {"error": "not_found", "path": path})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/v1/runs/select":
            try:
                body = self._read_json_body()
                out_base_value = body.get("out_base")
                if not isinstance(out_base_value, str) or not out_base_value.strip():
                    raise ValueError("out_base must be a non-empty string")
                snapshot = self.server.select_out_base(_repo_path(out_base_value))
                self._send_json(200, {
                    "selected_out_base": str(self.server.out_base),
                    "job_control": _job_snapshot(snapshot) if snapshot is not None else None,
                })
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "out_base_not_found", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": "run_switch_blocked", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            return
        if path.startswith("/v1/jobs/") and path.endswith("/relaunch"):
            job_id = unquote(path[len("/v1/jobs/") : -len("/relaunch")]).strip("/")
            current = self.server.get_job()
            if current is None or str(current.get("job_id") or "") != job_id:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            if current.get("state") == "running":
                self._send_json(409, {"error": "job_already_running", "job_id": current.get("job_id")})
                return
            workflow_status_path = Path(str(current.get("out_base") or "")) / "query_workflow" / "status.json"
            workflow_status_raw = _load_optional(workflow_status_path)
            if workflow_status_raw is None:
                self._send_json(404, {"error": "status_not_found", "job_id": job_id})
                return
            retry_rec: str | None = None
            workflow_status: dict[str, Any] | None = None
            receipts_path = Path(str(current.get("out_base") or "")) / "query_workflow" / "execution_receipts.jsonl"
            try:
                from check_workflow_retry_eligibility import build_eligibility_report, load_jsonl_objects

                receipts = load_jsonl_objects(receipts_path) if receipts_path.is_file() else []
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
            try:
                body = self._read_json_body()
                payload, request_source, request_dir, relaunch_context = _load_relaunch_request(
                    body,
                    out_base=Path(str(current.get("out_base") or "")),
                    workflow_status_raw=workflow_status_raw,
                    workflow_status=workflow_status,
                )
                _start_job_thread(self.server, payload=payload, request_source=request_source, request_dir=request_dir)
                snapshot = self._current_job_snapshot() or {}
                self._send_json(202, {
                    "job_id": snapshot.get("job_id"),
                    "state": snapshot.get("state"),
                    "started_at_utc": snapshot.get("started_at_utc"),
                    "out_base": snapshot.get("out_base"),
                    "relaunch_action": relaunch_context.get("relaunch_action"),
                    "source_job_id": job_id,
                })
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "request_not_found", "message": str(exc), "job_id": job_id})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc), "job_id": job_id})
            except SystemExit as exc:
                self._send_json(400, {"error": "validation_rejected", "message": str(exc), "job_id": job_id})
            return
        if path != "/v1/jobs/start":
            self._send_json(404, {"error": "not_found", "path": path})
            return
        current = self.server.get_job()
        if current is not None and current.get("state") == "running":
            self._send_json(409, {"error": "job_already_running", "job_id": current.get("job_id")})
            return
        try:
            body = self._read_json_body()
            payload, request_source, request_dir = _load_start_request(body, default_out_base=self.server.out_base)
            _start_job_thread(self.server, payload=payload, request_source=request_source, request_dir=request_dir)
            snapshot = self._current_job_snapshot() or {}
            self._send_json(202, {
                "job_id": snapshot.get("job_id"),
                "state": snapshot.get("state"),
                "started_at_utc": snapshot.get("started_at_utc"),
                "out_base": snapshot.get("out_base"),
            })
        except FileNotFoundError as exc:
            self._send_json(404, {"error": "request_not_found", "message": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": "invalid_request", "message": str(exc)})
        except SystemExit as exc:
            self._send_json(400, {"error": "validation_rejected", "message": str(exc)})


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
    ap.add_argument("--history-root", default="", help="Root directory for recent-run discovery (default: parent of out-base)")
    ap.add_argument("--history-limit", type=int, default=12, help="Number of recent runs shown in the admin shell")
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
    history_root = _repo_path(args.history_root) if args.history_root else out_base.parent
    if not history_root.is_dir():
        raise SystemExit(f"[ERROR] --history-root does not exist: {history_root}")

    server = DashboardServer(
        (args.bind_host, args.port),
        DashboardHandler,
        out_base=out_base,
        history_root=history_root,
        history_limit=max(1, args.history_limit),
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
        "history_root": str(history_root),
        "pid": os.getpid(),
    }))
    sys.stdout.flush()

    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
