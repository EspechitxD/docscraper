import { useEffect, type ReactNode } from "react";

export function Button({
  children,
  kind = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "secondary" | "ghost" | "danger" }) {
  return (
    <button className={`btn ${kind === "primary" ? "" : kind}`} {...props}>
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="lbl">
      {label}
      {children}
    </label>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "error" | "warn"; children: ReactNode }) {
  return <div className={`notice ${kind === "info" ? "" : kind}`}>{children}</div>;
}

export function Progress({ value, waiting = false }: { value: number; waiting?: boolean }) {
  const width = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const unknown = waiting && width <= 0;
  return (
    <div className="progress-line">
      <div
        className={`progress ${unknown ? "waiting" : ""}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={unknown ? undefined : width}
        aria-busy={waiting}
      >
        <span style={unknown ? undefined : { width: `${width}%` }} />
      </div>
      <span className="progress-label">{unknown ? "aguardando" : `${Math.round(width)}%`}</span>
    </div>
  );
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
