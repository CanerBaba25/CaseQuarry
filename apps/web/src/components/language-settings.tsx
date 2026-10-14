"use client";

import { useEffect, useId, useRef, useState } from "react";
import { locales, normalizeLanguage } from "../../../../packages/i18n";
import { api } from "@/lib/api";
import { uiText, type InterfaceMessage } from "@/lib/i18n";
import type { User } from "@/lib/types";
import { ErrorBox } from "./ui";
import { useInterfaceLanguage } from "./locale-provider";
import styles from "./language-settings.module.css";

type Props = { user?: User; saved?: (user: User) => void; compact?: boolean };
export function LanguageControl({ user, saved, compact = false }: Props) {
  const locale = useInterfaceLanguage();
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<InterfaceMessage>("");
  const identity = useRef(user?.id);
  identity.current = user?.id;
  const live = useRef(true);
  const id = useId();
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  async function choose(value: string) {
    const language = normalizeLanguage(value),
      actor = user?.id;
    setError(null);
    setMessage("");
    try {
      await locale.change(
        language,
        user
          ? async () => {
              const updated = await api<User>("/me/preferences", {
                method: "PATCH",
                body: JSON.stringify({ language }),
              });
              if (!live.current || identity.current !== actor) return false;
              saved?.(updated);
              setMessage("Language saved for your account.");
              return true;
            }
          : undefined,
      );
    } catch (failure) {
      if (live.current && identity.current === actor) setError(failure);
    }
  }
  return (
    <div className={compact ? styles.compact : styles.control}>
      <label htmlFor={id}>
        <span>{uiText(compact ? "Language" : "Interface language")}</span>
        <select
          id={id}
          aria-label={uiText("Choose your interface language")}
          value={locale.language}
          disabled={locale.loading}
          onChange={(event) => void choose(event.target.value)}
        >
          {locales.map((language) => (
            <option
              key={language.code}
              value={language.code}
              lang={language.code}
            >
              {language.nativeName}
            </option>
          ))}
        </select>
      </label>
      {locale.loading && !compact && (
        <p role="status">{uiText("Loading language…")}</p>
      )}
      {message && !compact && (
        <p className="notice green" role="status">
          {uiText(message)}
        </p>
      )}
      <ErrorBox error={error} />
      {Boolean(locale.error) && (
        <div className={styles.fallback} role="status">
          <p>
            {uiText(
              "English fallback is active because this language could not be loaded.",
            )}
          </p>
          <button
            type="button"
            className="text-link"
            onClick={() => void locale.activate(locale.language)}
          >
            {uiText("Try loading language again")}
          </button>
        </div>
      )}
    </div>
  );
}
export default function LanguageSettings(props: Props) {
  return (
    <section className={`panel ${styles.panel}`}>
      <h2>{uiText("Interface language")}</h2>
      <p>{uiText("Choose the language used for menus and controls.")}</p>
      <LanguageControl {...props} />
      <p className={styles.help}>
        {uiText(
          "Evidence, source text and names stay in their original language.",
        )}
      </p>
    </section>
  );
}
