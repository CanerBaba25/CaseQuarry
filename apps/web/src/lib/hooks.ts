"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
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
        if (!controller.signal.aborted) setError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, version]);
  return {
    data: dataPath === path ? data : null,
    error,
    loading,
    refresh,
    setData,
  };
}
