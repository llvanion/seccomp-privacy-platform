# Operator Console (SPA)

Single-page operator console for **seccomp-privacy-platform**. Vite + React + TypeScript + Tailwind.
Coordinates all 9 console sections against the 6 local sidecar HTTP APIs.

## Local development

```bash
cd console
npm ci          # or: npm install
npm run dev     # http://localhost:5173 with HMR + proxy to the dashboard
```

The dev server proxies the following paths to the operator-dashboard server
(default `http://127.0.0.1:18094`; override with `CONSOLE_DEV_PROXY_TARGET`):

- `/v1/*`
- `/healthz`
- `/metrics`

Bring the dashboard up in a second shell so the SPA has live data:

```bash
python3 ../scripts/serve_operator_dashboard.py \
  --out-base "$PWD/../tmp/sse_bridge_pipeline_demo" \
  --port 18094 \
  --bind-host 127.0.0.1
```

## Production build

```bash
npm run build   # writes ./dist
```

The dashboard server resolves `--console-dist` (or defaults to
`<repo>/console/dist`) and serves the SPA at `/` with SPA-fallback routing
to `index.html` for client-side routes.

## Theme switching

The console now ships with both dark and light themes.

- Use the top-right `白色 / 深色` toggle in the authenticated console header.
- The login page also exposes a `白色 UI / 深色 UI` toggle before sign-in.
- The chosen theme is persisted in browser `localStorage` under `console.theme`.
- `index.html` applies the saved theme before React boot so refreshes do not
  flash back to dark mode first.

The implementation keeps one Tailwind utility surface and swaps CSS variables
at the document root, so route-level components do not need duplicate theme
class trees.

## Demo entrypoint

For the self-contained defense demo, use the dashboard-served SPA rather than
the Vite dev server:

```bash
python3 ../scripts/prepare_defense_demo.py --out-dir ../tmp/defense_demo
bash ../scripts/start_defense_demo.sh "$PWD/../tmp/defense_demo"
```

Then open:

- `http://127.0.0.1:18094/`
- Main route: `http://127.0.0.1:18094/home`

If the browser cannot reach `127.0.0.1`, verify the browser and the terminal
are running on the same machine. The demo scripts bind the dashboard to loopback
by default.

## Sidecar API surface

| Sidecar              | Default port | Routes consumed                                                                 |
| -------------------- | ------------ | ------------------------------------------------------------------------------- |
| operator dashboard   | 18094        | `/v1/dashboard`, `/v1/jobs/*`, `/v1/requests/*`, `/v1/pjc-mtls/*`, `/v1/runs/*` |
| metadata             | 18090        | `/v1/jobs`, `/v1/entities/{tenants,datasets,services,callers,policies,…}`        |
| query workflow       | 18091        | `/v1/query-workflows/{dry-run,execute}`                                          |
| audit query          | 18092        | `/v1/public-report`, `/v1/audit-chain`, `/v1/observability`, `/v1/catalog-lineage` |
| platform health      | 18093        | `/v1/platform-health`                                                            |
| record recovery HTTP | auto         | `/healthz`, `/metrics`                                                           |

Configure non-default base URLs and Bearer tokens at runtime via the
`/settings` route in the SPA. Base URLs are stored in browser `localStorage`
(`seccomp.console.baseUrls.v1`). Bearer tokens are stored only in
`sessionStorage` for the current tab/session and are not persisted across
browser restarts.

## Routes

```
/home               · Per-tenant platform-health, alerts, KPIs, quick links
/jobs/*             · List, detail, start, relaunch
/requests/*         · Submit, list, detail, approve, reject
/sse-query          · Standalone SSE keyword search (drives scripts/sse_oneshot_search.py)
/pjc-only           · Standalone PJC on prepared bridge CSVs + policy_release (drives scripts/pjc_run_only.py)
/audit/*            · Public report · chain & seal · observability · lineage · external anchor
/catalog/*          · Tenants · datasets · services · lineage · e-commerce fact layer
/permissions/*      · Callers · policies · bindings · caller-permissions · keyring · KMS · OpenFGA
/recovery/*         · Service status · Prometheus metrics · PJC mTLS · TLS diagnostics
/observability/*    · Overview · events · alerts · Grafana links · chaos drills
/compliance/*       · GDPR matrix · threat model · reviewer 8-step checklist · license
/security/*         · Tamper detection · malformed-input gate · mTLS bench · hygiene · contracts · benchmarks
/settings           · Configure sidecar base URLs and tokens
```

## Project layout

```
console/
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.js
├── tsconfig.json
├── vite.config.ts
├── public/
└── src/
    ├── api/                 # typed HTTP clients per sidecar
    ├── components/          # design system: ui, layout, tabs, data-table, modal, toast
    ├── hooks/               # useApiQuery, useApiMutation
    ├── lib/                 # cx, format helpers
    ├── routes/              # one file per top-level route (plus nested sub-routes)
    ├── styles/              # tailwind base + globals
    ├── main.tsx
    └── router.tsx
```

## License

GPL-3.0-or-later. See repo root `LICENSE` and `NOTICE`.
