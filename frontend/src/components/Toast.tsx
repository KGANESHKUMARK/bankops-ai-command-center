import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "./ui";

type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

const ToastContext = createContext<((message: string, tone?: ToastTone) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((current) => current.filter((t) => t.id !== id)), []);
  const push = useCallback((message: string, tone: ToastTone = "info") => {
    const id = nextId.current++;
    setItems((current) => [...current.slice(-3), { id, tone, message }]);
    window.setTimeout(() => dismiss(id), tone === "error" ? 9000 : 6000);
  }, [dismiss]);
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" aria-atomic="false" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2">
        {items.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === "error" ? "alert" : "status"}
            className={cx(
              "pointer-events-auto flex items-start gap-2 rounded-md border px-3.5 py-2.5 text-sm shadow-lg",
              toast.tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-900",
              toast.tone === "error" && "border-red-200 bg-red-50 text-red-900",
              toast.tone === "info" && "border-slate-200 bg-white text-slate-800",
            )}
          >
            {toast.tone === "success" ? <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
              : toast.tone === "error" ? <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                : <Info className="mt-0.5 size-4 shrink-0" aria-hidden />}
            <span className="min-w-0 flex-1">{toast.message}</span>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(toast.id)} className="rounded p-0.5 opacity-70 hover:opacity-100">
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string, tone?: ToastTone) => void {
  const push = useContext(ToastContext);
  if (!push) throw new Error("useToast must be used inside <ToastProvider>");
  return push;
}
