"use client";
import { uiMessage, uiText, type InterfaceMessage } from "@/lib/i18n";

import { useEffect, useId, useState } from "react";
import { api, date, timeZoneSupported } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { ErrorBox, Icon, Loading } from "./ui";
import styles from "./time-zone-settings.module.css";

type TimeZones = { items: string[]; default: string; current: string };

export default function TimeZoneSettings({
  user,
  saved,
}: {
  user: User;
  saved: (user: User) => void;
}) {
  const zones = useResource<TimeZones>("/timezones");
  const [selected, setSelected] = useState(user.time_zone || "UTC");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<InterfaceMessage>("");
  const [now, setNow] = useState<string | null>(null);
  const id = useId();
  useEffect(() => {
    setSelected(user.time_zone || "UTC");
  }, [user.id, user.time_zone]);
  useEffect(() => {
    setNow(new Date().toISOString());
    const timer = setInterval(() => setNow(new Date().toISOString()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const allowed = zones.data?.items ?? [];
  const matching = allowed.filter((zone) =>
    zone
      .toLowerCase()
      .replaceAll("_", " ")
      .includes(query.toLowerCase().trim()),
  );
  const options = Array.from(new Set([selected, "UTC", ...matching]));
  const supported = timeZoneSupported(selected);
  function chooseDeviceZone() {
    const deviceZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!deviceZone || !allowed.includes(deviceZone)) {
      setError(
        new Error(
          "This device's timezone is not offered by your server. Choose a timezone from the list.",
        ),
      );
      return;
    }
    setSelected(deviceZone);
    setQuery("");
    setError(null);
    setMessage(
      uiMessage("Selected {0}. Save to apply it to your account.", {
        "0": deviceZone,
      }),
    );
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const updated = await api<User>("/me/preferences", {
        method: "PATCH",
        body: JSON.stringify({ time_zone: selected }),
      });
      saved(updated);
      setMessage(
        "Timezone saved for your account. Other connected clients will use this preference when they refresh.",
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className={`panel ${styles.panel}`}
      aria-labelledby={`${id}-title`}
    >
      <div className={styles.heading}>
        <span className={styles.icon}>
          <Icon name="clock" size={22} />
        </span>
        <div>
          <h2 id={`${id}-title`}>{uiText("Your timezone")}</h2>
          <p>
            {uiText(
              "Keep timestamps and your task calendar consistent across devices.",
            )}
          </p>
        </div>
        <span className={styles.current}>
          {user.time_zone || uiText("UTC")}
        </span>
      </div>
      <ErrorBox error={zones.error} retry={zones.refresh} />
      <ErrorBox error={error} />
      {zones.loading && !zones.data ? (
        <Loading text={uiText("Loading available timezones…")} />
      ) : (
        <form onSubmit={submit} className={styles.form}>
          <div className={styles.fields}>
            <label>
              {uiText("Find a timezone")}
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={uiText(
                  "Search a region or city, for example Toronto",
                )}
                maxLength={100}
                aria-describedby={`${id}-matching`}
              />
            </label>
            <label>
              {uiText("Timezone")}
              <select
                value={selected}
                onChange={(event) => {
                  setSelected(event.target.value);
                  setError(null);
                  setMessage("");
                }}
                aria-describedby={`${id}-help`}
                aria-label={uiText("Timezone")}
                disabled={!zones.data || busy}
              >
                {options.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className={styles.detail}>
            <small id={`${id}-matching`}>
              {uiText(
                "{0} matching zones. Your selected zone and UTC remain available.",
                { "0": matching.length },
              )}
            </small>
            <span>
              {now
                ? uiText("Current time: {0}", {
                    "0": date(now, true, selected),
                  })
                : ""}
            </span>
          </div>
          <p id={`${id}-help`} className={styles.help}>
            {uiText(
              "Saved to your account on the firm server. Date-only task deadlines keep their calendar date; raw evidence timestamps and UTC search boundaries are preserved.",
            )}
          </p>
          {!supported && (
            <p className="notice">
              {uiText(
                "This browser cannot display {0}. Timestamps fall back to UTC here; your saved preference remains available to supported clients.",
                { "0": selected },
              )}
            </p>
          )}
          <div className={styles.actions}>
            <button
              type="button"
              className="button secondary compact"
              disabled={!zones.data || busy}
              onClick={chooseDeviceZone}
            >
              <Icon name="clock" size={15} />
              {uiText("Use device timezone")}
            </button>
            <button
              type="submit"
              className="button primary compact"
              disabled={
                !zones.data || busy || selected === (user.time_zone || "UTC")
              }
            >
              {busy ? uiText("Saving timezone…") : uiText("Save timezone")}
            </button>
          </div>
          {message && (
            <p role="status" className={styles.message}>
              {uiText(message)}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
