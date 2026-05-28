import { NavLink } from "react-router-dom";
import { cx } from "@/lib/cx";

export type Tab = { to: string; label: string; end?: boolean; badge?: string };

export function RouteTabs({ tabs, className }: { tabs: Tab[]; className?: string }) {
  return (
    <div className={cx("flex flex-wrap gap-1 border-b border-line-subtle mb-4", className)}>
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            cx(
              "px-3 py-2 text-sm font-medium rounded-t-md border-b-2 -mb-px focus-ring",
              isActive
                ? "border-brand text-brand"
                : "border-transparent text-ink-muted hover:text-ink",
            )
          }
        >
          <span className="inline-flex items-center gap-2">
            {t.label}
            {t.badge != null && (
              <span className="pill-muted !py-0">{t.badge}</span>
            )}
          </span>
        </NavLink>
      ))}
    </div>
  );
}

export function StaticTabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: ReadonlyArray<{ id: T; label: string; badge?: string }>;
  value: T;
  onChange: (id: T) => void;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-wrap gap-1 border-b border-line-subtle mb-4", className)}>
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={cx(
            "px-3 py-2 text-sm font-medium rounded-t-md border-b-2 -mb-px focus-ring",
            t.id === value
              ? "border-brand text-brand"
              : "border-transparent text-ink-muted hover:text-ink",
          )}
        >
          <span className="inline-flex items-center gap-2">
            {t.label}
            {t.badge != null && <span className="pill-muted !py-0">{t.badge}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}
