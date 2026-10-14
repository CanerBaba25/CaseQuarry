"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  loadCatalog,
  normalizeLanguage,
  type Language,
} from "../../../../packages/i18n";
import { setInterfaceCatalog, uiText } from "@/lib/i18n";

type LocaleState = { language: Language; loading: boolean; error: unknown };
type LocaleContext = LocaleState & {
  activate: (language: string) => Promise<void>;
  change: (
    language: Language,
    persist?: () => Promise<boolean>,
  ) => Promise<boolean>;
};
const Context = createContext<LocaleContext | null>(null);

export default function LocaleProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<LocaleState>({
    language: "en",
    loading: false,
    error: null,
  });
  const revision = useRef(0);
  const changing = useRef(false);
  const load = useCallback(async (language: Language, request: number) => {
    try {
      const catalog = await loadCatalog(language);
      if (revision.current !== request) return;
      setInterfaceCatalog(language, catalog);
      setState({ language, loading: false, error: null });
    } catch (error) {
      if (revision.current !== request) return;
      setInterfaceCatalog(language, {});
      setState({ language, loading: false, error });
    }
  }, []);
  const activate = useCallback(
    async (value: string) => {
      const request = ++revision.current;
      changing.current = false;
      setState((current) => ({ ...current, loading: true, error: null }));
      await load(normalizeLanguage(value), request);
    },
    [load],
  );
  const change = useCallback(
    async (language: Language, persist?: () => Promise<boolean>) => {
      if (changing.current) return false;
      changing.current = true;
      const request = ++revision.current;
      setState((current) => ({ ...current, loading: true, error: null }));
      try {
        if (persist && !(await persist())) return false;
        if (revision.current !== request) return false;
        await load(language, request);
        return true;
      } finally {
        if (revision.current === request) {
          changing.current = false;
          setState((current) => ({ ...current, loading: false }));
        }
      }
    },
    [load],
  );
  useEffect(() => {
    document.documentElement.lang = state.language;
    document.title = uiText("CaseQuarry — Evidence workspace");
  }, [state.language, state.error, state.loading]);
  return (
    <Context.Provider value={{ ...state, activate, change }}>
      {children}
    </Context.Provider>
  );
}
export function useInterfaceLanguage() {
  const value = useContext(Context);
  if (!value) throw new Error("Interface language provider is missing.");
  return value;
}
