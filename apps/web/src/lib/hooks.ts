"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { RefreshScope } from "./sync";

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [errorPath, setErrorPath] = useState<string | null>(null);
  const [requestedPath, setRequestedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    function receive(event: Event) {
      const scope = (event as CustomEvent<RefreshScope>).detail;
      const prefix = scope.caseId ? `/cases/${scope.caseId}` : null;
      if (!path || (!scope.system && (!prefix || !(path === prefix || path.startsWith(`${prefix}/`))))) return;
      if (scope.clear) {
        setData(null);
        setDataPath(null);
        setError(null);
        setErrorPath(null);
      }
      refresh();
    }
    window.addEventListener("cq:refresh", receive);
    return () => window.removeEventListener("cq:refresh", receive);
  }, [path, refresh]);
  useEffect(() => {
    if (!path) {
      setData(null);
      setDataPath(null);
      setError(null);
      setErrorPath(null);
      setRequestedPath(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setRequestedPath(path);
    setLoading(true);
    setError(null);
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setData(value);
          setDataPath(path);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setError(error);
          setErrorPath(path);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, version]);
  return {
    data: dataPath === path ? data : null,
    error: path && errorPath === path ? error : null,
    loading: Boolean(path) && (requestedPath !== path || loading),
    refresh,
    setData,
  };
}
