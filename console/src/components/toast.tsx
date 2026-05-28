import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import type { StatusKind } from "./ui";

type Toast = {
  id: string;
  kind: StatusKind;
  title: string;
  description?: string;
  timeoutMs?: number;
};

type ToastContextValue = {
  push: (toast: Omit<Toast, "id">) => void;
  pushError: (title: string, description?: string) => void;
  pushSuccess: (title: string, description?: string) => void;
};

const Ctx = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const counter = useRef(0);

  const remove = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    counter.current += 1;
    const id = `t${counter.current}`;
    setItems((prev) => [...prev, { ...toast, id }]);
    const timeoutMs = toast.timeoutMs ?? (toast.kind === "err" ? 8000 : 4500);
    window.setTimeout(() => remove(id), timeoutMs);
  }, [remove]);

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      pushError: (title, description) => push({ kind: "err", title, description }),
      pushSuccess: (title, description) => push({ kind: "ok", title, description }),
    }),
    [push],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {items.map((t) => (
          <ToastItem key={t.id} toast={t} onClose={() => remove(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const accent = toast.kind === "ok" ? "border-l-accent-ok" : toast.kind === "err" ? "border-l-accent-err" : toast.kind === "warn" ? "border-l-accent-warn" : "border-l-brand";
  return (
    <div className={cx("panel pl-3.5 pr-3 py-2.5 border-l-4 shadow-elevated animate-in fade-in", accent)}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink">{toast.title}</div>
          {toast.description && <div className="text-2xs text-ink-muted mt-0.5 break-words">{toast.description}</div>}
        </div>
        <button
          className="text-ink-dim hover:text-ink text-lg leading-none focus-ring"
          aria-label="dismiss"
          onClick={onClose}
        >
          ×
        </button>
      </div>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

// Provide a no-op outside provider (used very rarely in tests / errors).
export function useOptionalToast(): ToastContextValue {
  const ctx = useContext(Ctx);
  if (ctx) return ctx;
  return {
    push: () => undefined,
    pushError: () => undefined,
    pushSuccess: () => undefined,
  };
}

// Workaround for missing animate-in plugin; let's not depend on tailwindcss-animate.
// We keep an empty hook here to make this module importable.
export function useToastBootstrap() {
  useEffect(() => undefined, []);
}
