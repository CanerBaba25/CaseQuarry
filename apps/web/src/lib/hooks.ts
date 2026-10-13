"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";
import { api, ApiError } from "./api";
import type { RefreshScope } from "./sync";

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [errorPath, setErrorPath] = useState<string | null>(null);
  const [requestedPath, setRequestedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [version, setVersion] = useState(0);
  const activeRequest = useRef<{
    path: string;
    controller: AbortController;
  } | null>(null);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  const updateData = useCallback(
    (value: SetStateAction<T | null>) => {
      const request = activeRequest.current;
      if (request?.path === path) {
        // An acknowledged mutation supersedes a read started before that save.
        request.controller.abort();
        activeRequest.current = null;
        setLoading(false);
      }
      setData(value);
    },
    [path],
  );
  useEffect(() => {
    function receive(event: Event) {
      const scope = (event as CustomEvent<RefreshScope>).detail || {
        system: true,
      };
      const prefix = scope.caseId ? `/cases/${scope.caseId}` : null;
      if (
        !path ||
        (!scope.system &&
          (!prefix || !(path === prefix || path.startsWith(`${prefix}/`))))
      )
        return;
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
    activeRequest.current = { path, controller };
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
          if (
            error instanceof ApiError &&
            [401, 403, 404].includes(error.status)
          ) {
            setData(null);
            setDataPath(null);
          }
          setError(error);
          setErrorPath(path);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (activeRequest.current?.controller === controller)
        activeRequest.current = null;
    };
  }, [path, version]);
  return {
    data: dataPath === path ? data : null,
    error: path && errorPath === path ? error : null,
    loading: Boolean(path) && (requestedPath !== path || loading),
    refresh,
    setData: updateData,
  };
}
