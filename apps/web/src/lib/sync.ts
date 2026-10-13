"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "./api";

export type RefreshScope = {
  caseId?: string;
  system?: boolean;
  clear?: boolean;
};
type Revision = {
  tenant_revision: number;
  case_revision: number | null;
  progress_revision: string | null;
};
export type SyncState =
  "checking" | "connected" | "reconnecting" | "unavailable";

function announce(detail: RefreshScope) {
  window.dispatchEvent(new CustomEvent<RefreshScope>("cq:refresh", { detail }));
}

export function useFirmSync(
  userId: string | null,
  caseId: string | null,
  refreshUser: () => void,
) {
  const [state, setState] = useState<SyncState>("checking");
  useEffect(() => {
    if (!userId) return;
    const controller = new AbortController();
    let previous: Revision | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let running = false;
    setState("checking");
    async function poll() {
      if (running || controller.signal.aborted) return;
      running = true;
      try {
        const current = await api<Revision>(
          `/sync${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ""}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        // The first revision also refreshes mounted reads: a mutation may have
        // committed between their initial request and this sync baseline.
        const system =
          previous === null ||
          current.tenant_revision !== previous.tenant_revision;
        const matter =
          previous === null ||
          current.case_revision !== previous.case_revision ||
          current.progress_revision !== previous.progress_revision;
        if (system || matter)
          announce({ system, caseId: matter && caseId ? caseId : undefined });
        if (system && previous !== null) refreshUser();
        previous = current;
        setState("connected");
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          setState("unavailable");
          announce({ system: true, clear: true });
          refreshUser();
          controller.abort();
        } else if (
          error instanceof ApiError &&
          error.status === 404 &&
          caseId
        ) {
          setState("unavailable");
          announce({ caseId, system: true, clear: true });
        } else setState("reconnecting");
      } finally {
        running = false;
        if (!controller.signal.aborted)
          timer = setTimeout(() => void poll(), document.hidden ? 30000 : 5000);
      }
    }
    function wake() {
      if (!document.hidden && !running) {
        clearTimeout(timer);
        void poll();
      }
    }
    void poll();
    window.addEventListener("online", wake);
    window.addEventListener("focus", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener("online", wake);
      window.removeEventListener("focus", wake);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [userId, caseId, refreshUser]);
  return state;
}
