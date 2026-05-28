import { useState } from "react";
import { NavLink, Outlet, useNavigation } from "react-router-dom";
import {
  Activity,
  BadgeCheck,
  BookOpen,
  Boxes,
  Calculator,
  ClipboardList,
  Database,
  FileLock2,
  GanttChartSquare,
  HardDrive,
  Home,
  KeyRound,
  Network,
  Radar,
  Search,
  Settings,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";

import { cx } from "@/lib/cx";

type NavEntry = {
  to: string;
  label: string;
  description: string;
  icon: typeof Home;
  end?: boolean;
};

const NAV_GROUPS: Array<{ label: string; items: NavEntry[] }> = [
  {
    label: "运营",
    items: [
      { to: "/home", label: "首页 / 健康", description: "Per-tenant health, alerts", icon: Home, end: true },
      { to: "/jobs", label: "作业", description: "Jobs lifecycle", icon: GanttChartSquare },
      { to: "/requests", label: "请求工作流", description: "Submit / approve queries", icon: ClipboardList },
      { to: "/sse-query", label: "SSE 查询", description: "One-shot keyword search", icon: Search },
      { to: "/pjc-only", label: "PJC 求交", description: "Standalone PJC on prepared CSVs", icon: Calculator },
    ],
  },
  {
    label: "数据治理",
    items: [
      { to: "/catalog", label: "目录 / 血缘", description: "Tenants, datasets, services", icon: Boxes },
      { to: "/permissions", label: "权限 / IAM / KMS", description: "Policies, keys, OpenFGA", icon: KeyRound },
      { to: "/recovery", label: "记录恢复 / mTLS", description: "Service status + PJC mTLS", icon: Network },
    ],
  },
  {
    label: "审计与安全",
    items: [
      { to: "/audit", label: "审计", description: "Audit chain, public report, anchor sinks", icon: FileLock2 },
      { to: "/observability", label: "可观测性", description: "Metrics, alerts, chaos drills", icon: Activity },
      { to: "/compliance", label: "合规", description: "GDPR, threat model, checklist", icon: BookOpen },
      { to: "/security", label: "安全工具", description: "Tamper, gates, benchmarks", icon: ShieldCheck },
    ],
  },
  {
    label: "系统",
    items: [{ to: "/settings", label: "设置", description: "Tokens, base URLs", icon: Settings }],
  },
];

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigation = useNavigation();
  const isLoading = navigation.state === "loading";

  return (
    <div className={cx("min-h-screen grid", collapsed ? "grid-cols-[64px_1fr]" : "grid-cols-[260px_1fr]")}
    >
      <Sidebar collapsed={collapsed} toggle={() => setCollapsed((c) => !c)} />
      <main className="flex flex-col min-w-0">
        <Topbar isLoading={isLoading} />
        <div className="flex-1 p-6 overflow-x-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Sidebar({ collapsed, toggle }: { collapsed: boolean; toggle: () => void }) {
  return (
    <aside className="sticky top-0 h-screen border-r border-line bg-bg-panel/95 backdrop-blur flex flex-col">
      <div className="px-4 py-5 flex items-center gap-2.5 border-b border-line-subtle">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand to-brand-subtle grid place-items-center text-bg font-extrabold shadow-glow">
          PJ
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="text-sm font-bold text-ink leading-tight">PJC × SSE</div>
            <div className="text-2xs text-ink-muted truncate">Operator Console</div>
          </div>
        )}
        <button
          onClick={toggle}
          aria-label="toggle sidebar"
          className="ml-auto text-ink-dim hover:text-ink focus-ring rounded p-1"
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3 flex flex-col gap-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <div className="px-2 py-1 text-2xs uppercase tracking-wider text-ink-dim">{group.label}</div>
            )}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cx(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm focus-ring transition-colors",
                        isActive
                          ? "bg-brand/12 text-brand"
                          : "text-ink-muted hover:bg-bg-elevated/60 hover:text-ink",
                      )
                    }
                    title={collapsed ? `${item.label} — ${item.description}` : undefined}
                  >
                    <item.icon className="w-4 h-4 shrink-0" />
                    {!collapsed && (
                      <div className="min-w-0 flex-1">
                        <div className="truncate leading-tight">{item.label}</div>
                        <div className="text-2xs text-ink-dim truncate">{item.description}</div>
                      </div>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-line-subtle text-2xs text-ink-muted">
        {!collapsed ? (
          <>
            <div className="flex items-center gap-1.5">
              <BadgeCheck className="w-3.5 h-3.5 text-accent-ok" />
              GPL-3.0-or-later
            </div>
            <div className="mt-1 text-ink-dim">seccomp-privacy-platform</div>
          </>
        ) : (
          <BadgeCheck className="w-3.5 h-3.5 text-accent-ok mx-auto" />
        )}
      </div>
    </aside>
  );
}

function Topbar({ isLoading }: { isLoading: boolean }) {
  return (
    <div className="sticky top-0 z-10 border-b border-line bg-bg/80 backdrop-blur">
      <div className="flex items-center gap-3 px-6 py-3">
        <Radar className={cx("w-4 h-4", isLoading ? "text-brand animate-pulse" : "text-ink-dim")} />
        <div className="text-2xs text-ink-muted font-mono">
          {isLoading ? "loading…" : "ready"}
        </div>
        <div className="ml-auto flex items-center gap-3 text-2xs text-ink-muted">
          <TopbarBadge icon={Database} label="metadata" port="18090" />
          <TopbarBadge icon={TerminalSquare} label="query" port="18091" />
          <TopbarBadge icon={FileLock2} label="audit" port="18092" />
          <TopbarBadge icon={Activity} label="health" port="18093" />
          <TopbarBadge icon={HardDrive} label="recovery" port="auto" />
        </div>
      </div>
    </div>
  );
}

function TopbarBadge({ icon: Icon, label, port }: { icon: typeof Home; label: string; port: string }) {
  return (
    <div className="hidden lg:flex items-center gap-1 px-2 py-1 rounded-md bg-bg-elevated border border-line-subtle">
      <Icon className="w-3 h-3 text-ink-dim" />
      <span className="font-mono">{label}</span>
      <span className="text-ink-dim">:{port}</span>
    </div>
  );
}
