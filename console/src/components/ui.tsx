import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

// ---------- Button ----------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type ButtonSize = "sm" | "md" | "lg";

const buttonVariantStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-brand text-bg font-semibold hover:bg-brand/90 focus-visible:bg-brand/90 shadow-card",
  secondary:
    "bg-bg-elevated text-ink border border-line hover:border-brand/50 hover:text-brand",
  ghost: "text-ink-muted hover:text-ink hover:bg-bg-elevated/60",
  danger: "bg-accent-err/15 text-accent-err border border-accent-err/30 hover:bg-accent-err/25",
  outline:
    "bg-transparent text-ink border border-line hover:border-brand/60 hover:text-brand",
};

const buttonSizeStyles: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs rounded-md",
  md: "h-9 px-3.5 text-sm rounded-lg",
  lg: "h-11 px-5 text-base rounded-xl",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, leftIcon, rightIcon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap transition-colors focus-ring disabled:opacity-50 disabled:cursor-not-allowed",
        buttonSizeStyles[size],
        buttonVariantStyles[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
});

// ---------- Input ----------

type InputProps = InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean };

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cx(
        "w-full h-9 px-3 rounded-lg bg-bg-subtle border border-line text-ink placeholder:text-ink-dim text-sm",
        "focus-ring focus-visible:border-brand/60",
        invalid && "border-accent-err/60",
        className,
      )}
      {...rest}
    />
  );
});

// ---------- Textarea ----------

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={cx(
          "w-full min-h-[88px] px-3 py-2 rounded-lg bg-bg-subtle border border-line text-ink placeholder:text-ink-dim text-sm font-mono",
          "focus-ring focus-visible:border-brand/60",
          className,
        )}
        {...rest}
      />
    );
  },
);

// ---------- Select ----------

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select
        ref={ref}
        className={cx(
          "w-full h-9 px-2.5 pr-8 rounded-lg bg-bg-subtle border border-line text-ink text-sm appearance-none",
          "focus-ring focus-visible:border-brand/60 cursor-pointer",
          "bg-[length:14px] bg-no-repeat bg-[right_8px_center] bg-[image:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2392a2b6' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>\")]",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
    );
  },
);

// ---------- Field wrapper ----------

export function Field({
  label,
  hint,
  error,
  children,
  className,
  required,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
  required?: boolean;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      {label && (
        <label className="field-label flex items-center gap-1">
          {label}
          {required && <span className="text-accent-err">*</span>}
        </label>
      )}
      {children}
      {hint && !error && <span className="text-2xs text-ink-muted">{hint}</span>}
      {error && <span className="text-2xs text-accent-err">{error}</span>}
    </div>
  );
}

// ---------- Card ----------

export function Card({ className, children }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("panel p-4", className)}>{children}</div>;
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex items-start justify-between gap-3 pb-3 border-b border-line-subtle mb-3", className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {description && <p className="text-2xs text-ink-muted mt-0.5">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

// ---------- Status pill ----------

export type StatusKind = "ok" | "warn" | "err" | "info" | "muted";

const statusClass: Record<StatusKind, string> = {
  ok: "pill-ok",
  warn: "pill-warn",
  err: "pill-err",
  info: "pill-info",
  muted: "pill-muted",
};

export function StatusPill({
  kind,
  children,
  className,
}: {
  kind: StatusKind;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx(statusClass[kind], className)}>
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

export function inferStatusKind(value: string | null | undefined): StatusKind {
  if (!value) return "muted";
  const lc = value.toLowerCase();
  if (["ok", "ready", "allow", "allowed", "success", "succeeded", "active", "released", "approved", "passed", "healthy", "true"].includes(lc)) return "ok";
  if (["warn", "warning", "pending", "pending_external_anchor", "running", "preparing", "in_progress", "queued"].includes(lc)) return "warn";
  if (["err", "error", "fail", "failed", "blocked", "deny", "denied", "rejected", "broken", "unhealthy", "false"].includes(lc)) return "err";
  if (["info", "noop", "skipped", "neutral"].includes(lc)) return "info";
  return "muted";
}

// ---------- Loading skeleton ----------

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("rounded-md shimmer", className)} />;
}

// ---------- Empty state ----------

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6">
      {icon && <div className="text-ink-dim mb-3">{icon}</div>}
      <h4 className="text-sm font-semibold text-ink">{title}</h4>
      {description && <p className="text-2xs text-ink-muted mt-1 max-w-md">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ---------- Error banner ----------

export function ErrorBanner({ title, message, retry }: { title?: string; message: ReactNode; retry?: () => void }) {
  return (
    <div className="panel p-4 border-accent-err/30 bg-accent-err/8">
      <div className="flex items-start gap-3">
        <div className="w-2 h-2 rounded-full bg-accent-err mt-1.5" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink">{title ?? "出错了"}</div>
          <div className="text-2xs text-ink-muted mt-1 break-words">{message}</div>
        </div>
        {retry && (
          <Button variant="ghost" size="sm" onClick={retry}>
            重试
          </Button>
        )}
      </div>
    </div>
  );
}

// ---------- Stat tile ----------

export function StatTile({
  label,
  value,
  hint,
  kind = "muted",
  icon,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  kind?: StatusKind;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("panel p-4 relative overflow-hidden", className)}>
      {icon && <div className="absolute right-3 top-3 text-ink-dim">{icon}</div>}
      <div className="field-label">{label}</div>
      <div className="text-2xl font-bold text-ink mt-2">{value}</div>
      {hint && (
        <div className="text-2xs mt-2 flex items-center gap-1.5">
          <StatusPill kind={kind} className="!py-0">
            {kind}
          </StatusPill>
          <span className="text-ink-muted">{hint}</span>
        </div>
      )}
    </div>
  );
}

// ---------- Section header ----------

export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: ReactNode;
}) {
  return (
    <header className="mb-6">
      {breadcrumbs && <div className="text-2xs text-ink-muted mb-2">{breadcrumbs}</div>}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
          {description && <p className="text-sm text-ink-muted mt-1 max-w-3xl">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </header>
  );
}

// ---------- JSON viewer ----------

const JSON_BLOCK_MAX_HEIGHT_CLASS: Record<string, string> = {
  "160px": "max-h-[160px]",
  "220px": "max-h-[220px]",
  "240px": "max-h-[240px]",
  "260px": "max-h-[260px]",
  "280px": "max-h-[280px]",
  "320px": "max-h-[320px]",
  "360px": "max-h-[360px]",
  "380px": "max-h-[380px]",
  "420px": "max-h-[420px]",
  "480px": "max-h-[480px]",
};

export function JsonBlock({ data, className, maxHeight }: { data: unknown; className?: string; maxHeight?: string }) {
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre
      className={cx(
        "panel p-3 font-mono text-2xs whitespace-pre-wrap break-words overflow-auto text-ink-muted",
        maxHeight && JSON_BLOCK_MAX_HEIGHT_CLASS[maxHeight],
        className,
      )}
    >
      {text}
    </pre>
  );
}

export function JsonDetails({
  title = "原始 JSON",
  data,
  maxHeight = "320px",
  defaultOpen = false,
}: {
  title?: ReactNode;
  data: unknown;
  maxHeight?: string;
  defaultOpen?: boolean;
}) {
  return (
    <details className="panel p-3" open={defaultOpen}>
      <summary className="cursor-pointer text-2xs text-ink-muted hover:text-ink select-none">
        {title}
      </summary>
      <JsonBlock data={data} className="mt-3" maxHeight={maxHeight} />
    </details>
  );
}

export function KeyValueGrid({
  items,
  columns = 2,
}: {
  items: Array<{ label: ReactNode; value: ReactNode }>;
  columns?: 2 | 3 | 4;
}) {
  const className =
    columns === 4 ? "grid-cols-2 sm:grid-cols-4" :
    columns === 3 ? "grid-cols-2 sm:grid-cols-3" :
    "grid-cols-2";
  return (
    <div className={cx("grid gap-3 text-2xs", className)}>
      {items.map((item, index) => (
        <div key={index} className="panel-soft p-3 rounded-lg">
          <div className="field-label">{item.label}</div>
          <div className="text-sm font-semibold text-ink mt-1 break-words">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

// ---------- Tag list ----------

export function TagList({ items, max = 6 }: { items: Array<string | null | undefined>; max?: number }) {
  const clean = items.filter((x): x is string => !!x);
  const shown = clean.slice(0, max);
  const hidden = clean.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((item) => (
        <span key={item} className="pill-muted">
          {item}
        </span>
      ))}
      {hidden > 0 && <span className="pill-muted">+{hidden}</span>}
    </div>
  );
}
