"use client";

import { useEffect, useId, useRef } from "react";
import { ApiError, label } from "@/lib/api";

const paths: Record<string, React.ReactNode> = {
  matters: (
    <>
      <rect x="3" y="5" width="18" height="15" rx="2" />
      <path d="M3 9h18M8 5V3h8v2" />
    </>
  ),
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  list: <path d="M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5" />
    </>
  ),
  people: (
    <>
      <circle cx="9" cy="7" r="3" />
      <path d="M3 21v-3a6 6 0 0 1 12 0v3m0-17a3 3 0 0 1 0 6m4 11v-3a6 6 0 0 0-3-5" />
    </>
  ),
  timeline: (
    <>
      <path d="M7 3v18m4-16h9m-9 7h7m-7 7h9" />
      <circle cx="7" cy="5" r="2" />
      <circle cx="7" cy="12" r="2" />
      <circle cx="7" cy="19" r="2" />
    </>
  ),
  check: <path d="m5 12 4 4L20 5" />,
  review: (
    <>
      <path d="M9 3H5v18h14V3h-4M9 2h6v4H9zM8 13l3 3 5-6" />
    </>
  ),
  export: (
    <>
      <path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5" />
    </>
  ),
  shield: (
    <>
      <path d="m12 2 8 3v6c0 6-8 11-8 11S4 17 4 11V5z" />
      <path d="m8 11 3 3 5-6" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="m9 3-1 3-3 1v3l-2 2 2 2v3l3 1 1 3h6l1-3 3-1v-3l2-2-2-2V7l-3-1-1-3z" />
    </>
  ),
  plus: <path d="M12 4v16M4 12h16" />,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  back: <path d="M20 12H4m6-6-6 6 6 6" />,
  file: (
    <>
      <path d="M14 2H5v20h14V7zM14 2v5h5M8 12h8m-8 4h6" />
    </>
  ),
  email: (
    <>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m2 6 10 7L22 6" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  close: <path d="m6 6 12 12M6 18 18 6" />,
  filter: <path d="M3 4h18l-7 8v7l-4 2v-9z" />,
  star: <path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z" />,
  copy: (
    <>
      <rect x="8" y="8" width="13" height="13" rx="1" />
      <path d="M16 8V3H3v13h5" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3 2 21h20zM12 8v6m0 3v1" />
    </>
  ),
  logout: (
    <>
      <path d="M9 3H3v18h6m5-15 6 6-6 6m-7-6h13" />
    </>
  ),
  menu: <path d="M3 5h18M3 12h18M3 19h18" />,
  moon: <path d="M21 14A9 9 0 0 1 10 3a9 9 0 1 0 11 11" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2" />
    </>
  ),
  network: (
    <>
      <circle cx="12" cy="4" r="2" />
      <circle cx="4" cy="18" r="2" />
      <circle cx="20" cy="18" r="2" />
      <path d="m11 6-6 10m8-10 6 10M6 18h12" />
    </>
  ),
  sparkle: (
    <>
      <path d="m12 3 2 6 6 3-6 2-2 7-2-7-7-2 7-3zM20 2v4m-2-2h4" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {paths[name] || paths.file}
    </svg>
  );
}

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "small" : ""}`}>
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 28 28" fill="none">
          <path d="M5 4h18v20H5z" stroke="currentColor" strokeWidth="2" />
          <path d="m10 9 8 5-8 5z" fill="currentColor" />
        </svg>
      </span>
      <span>
        CaseQuarry<span className="brand-subtitle">EVIDENCE WORKSPACE</span>
      </span>
    </div>
  );
}

export function Badge({ value, tone }: { value: string; tone?: string }) {
  const kind =
    tone ||
    (
      {
        indexed: "green",
        responsive: "green",
        verified: "green",
        completed: "green",
        active: "green",
        failed: "red",
        integrity_failed: "red",
        confirmed: "red",
        unsupported: "amber",
        partial: "amber",
        suspected: "amber",
        needs_review: "amber",
        pending: "amber",
        unreviewed: "neutral",
        none: "neutral",
      } as Record<string, string>
    )[value.toLowerCase()] ||
    "neutral";
  return <span className={`badge ${kind}`}>{label(value)}</span>;
}

export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="error-box" role="alert">
      <Icon name="alert" />
      <div>
        <strong>{message}</strong>
        {error instanceof ApiError && error.requestId && (
          <small>Request: {error.requestId}</small>
        )}
        {error instanceof ApiError && error.retryAfterSeconds !== undefined && (
          <small>
            The server requested a {error.retryAfterSeconds}-second pause before
            retrying this request.
          </small>
        )}
      </div>
      {retry && (
        <button
          type="button"
          className="button secondary compact"
          onClick={retry}
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function Loading({ text = "Loading workspace…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {text}
    </div>
  );
}

export function Empty({
  icon = "file",
  title,
  text,
  children,
}: {
  icon?: string;
  title: string;
  text: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {children}
    </div>
  );
}

let modalCount = 0;
let modalBodyOverflow = "";

export function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    if (modalCount === 0) modalBodyOverflow = document.body.style.overflow;
    modalCount += 1;
    document.body.style.overflow = "hidden";
    const focusables = () =>
      Array.from(
        ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]',
        ) || [],
      ).filter((element) => element.getClientRects().length > 0);
    focusables()[0]?.focus();
    function key(event: KeyboardEvent) {
      const dialogs = document.querySelectorAll("[data-cq-modal]");
      if (dialogs[dialogs.length - 1] !== ref.current) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key === "Tab") {
        const items = focusables();
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      modalCount -= 1;
      if (modalCount === 0) document.body.style.overflow = modalBodyOverflow;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={ref}
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-cq-modal="true"
      >
        <div className="modal-heading">
          <h2 id={titleId}>{title}</h2>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={close}
          >
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
