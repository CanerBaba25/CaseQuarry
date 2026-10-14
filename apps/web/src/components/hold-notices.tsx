"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, date, number, post } from "@/lib/api";
import { uiText, type MessageKey } from "@/lib/i18n";
import { useMountedRef, useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Matter } from "@/lib/types";
import { Empty, ErrorBox, Loading, Modal } from "./ui";
import { Pagination } from "./matter-pages";
import styles from "./hold-notices.module.css";

type NoticeState = "draft" | "issued" | "acknowledged";
type Notice = {
  id: string;
  case_id: string;
  hold_id: string;
  custodian_id: string;
  custodian_name: string;
  version: number;
  state: NoticeState;
  notice_text_sha256: string;
  created_at: string;
  updated_at: string;
  issued_at: string | null;
  acknowledgement_name: string | null;
  acknowledged_at: string | null;
  reminder_count: number;
  last_reminded_at: string | null;
  next_reminder_date: string | null;
};
type NoticeDetail = Notice & {
  notice_text: string;
  hold_state: string;
  server_today: string;
  time_zone: string;
};
type NoticePage = {
  items: Notice[];
  next_cursor: string | null;
  summary: Record<
    | "total"
    | "draft"
    | "issued"
    | "acknowledged"
    | "pending_acknowledgement"
    | "overdue"
    | "reminders",
    number
  >;
  hold_state: string;
  server_today: string;
  time_zone: string;
};
const states: Record<NoticeState, MessageKey> = {
  draft: "Draft notice",
  issued: "Issued notice",
  acknowledged: "Acknowledged notice",
};
const historyLabels: Record<string, MessageKey> = {
  "hold_notice.created": "Draft notice",
  "hold_notice.updated": "Notice record updated.",
  "hold_notice.issued": "Issued notice",
  "hold_notice.acknowledged": "Acknowledged notice",
  "hold_notice.reminded": "Recorded reminders",
};
const manualMessage =
  "Manual records only. CaseQuarry does not send notices or reminders, verify recipients, or determine legal sufficiency.";

function useVisibleRefresh(refresh: () => void) {
  useEffect(() => {
    const run = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const timer = setInterval(run, 15000);
    document.addEventListener("visibilitychange", run);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [refresh]);
}

export default function HoldNotices(props: {
  matter: Matter;
  hold: { id: string; name: string };
  close: () => void;
}) {
  return (
    <NoticeRegister key={`${props.matter.id}:${props.hold.id}`} {...props} />
  );
}

function NoticeRegister({
  matter,
  hold,
  close,
}: {
  matter: Matter;
  hold: { id: string; name: string };
  close: () => void;
}) {
  const path = `/cases/${matter.id}/holds/${hold.id}/notices`;
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState<(string | null)[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [create, setCreate] = useState(false);
  const access = useResource<Matter>(`/cases/${matter.id}`);
  const records = useResource<NoticePage>(
    `${path}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  useVisibleRefresh(records.refresh);
  useVisibleRefresh(access.refresh);
  const invalid =
    records.error instanceof ApiError &&
    records.error.code === "HOLD_NOTICE_CURSOR_INVALID";
  const data = invalid ? null : records.data;
  const editable = Boolean(
    data?.hold_state === "active" &&
    access.data &&
    can(access.data.role, "hold") &&
    !access.data.archived_at,
  );
  function restart() {
    setCursor(null);
    setPages([]);
    records.refresh();
    access.refresh();
  }
  return (
    <Modal title={uiText("Preservation notices")} close={close} wide>
      <div className={styles.heading}>
        <div>
          <h3>{hold.name}</h3>
          <p className="field-help">{uiText(manualMessage)}</p>
        </div>
        <div className={styles.actions}>
          <button
            className="button secondary"
            disabled={records.loading}
            onClick={restart}
          >
            {uiText("Refresh")}
          </button>
          <button
            className="button primary"
            disabled={!editable || records.loading}
            onClick={() => setCreate(true)}
          >
            {uiText("Register notice")}
          </button>
        </div>
      </div>
      <ErrorBox error={records.error || access.error} retry={restart} />
      {data && (
        <>
          {data.hold_state !== "active" && (
            <p className="notice">
              {uiText(
                "This hold is released. Its notice register is read-only.",
              )}
            </p>
          )}
          <dl className={styles.summary}>
            {(
              [
                ["total", "Total notices"],
                ["draft", "Draft notice"],
                ["issued", "Awaiting acknowledgement"],
                ["acknowledged", "Acknowledged notice"],
                ["overdue", "Overdue reminders"],
                ["reminders", "Recorded reminders"],
              ] as const
            ).map(([key, text]) => (
              <div key={key}>
                <dt>{uiText(text)}</dt>
                <dd>{number(data.summary[key])}</dd>
              </div>
            ))}
          </dl>
          <p className="field-help">
            {uiText(
              "Counts cover the entire notice register. Overdue reminders are before {0} in {1}.",
              { "0": date(data.server_today), "1": data.time_zone },
            )}
          </p>
        </>
      )}
      {records.loading && !data ? (
        <Loading />
      ) : (
        data &&
        (!data.items.length ? (
          <Empty
            icon="file"
            title={uiText("No notices recorded")}
            text={uiText(
              "Register a custodian notice, then record delivery and acknowledgement through your separate professional process.",
            )}
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{uiText("Custodian")}</th>
                  <th>{uiText("Status")}</th>
                  <th>{uiText("Next reminder date")}</th>
                  <th>{uiText("Recorded reminders")}</th>
                  <th>
                    <span className="sr-only">{uiText("Actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.custodian_name}</td>
                    <td>{uiText(states[row.state])}</td>
                    <td>
                      {date(row.next_reminder_date)}
                      {row.state === "issued" &&
                        row.next_reminder_date &&
                        row.next_reminder_date < data.server_today && (
                          <small className={styles.overdue}>
                            {uiText("Overdue")}
                          </small>
                        )}
                    </td>
                    <td>{number(row.reminder_count)}</td>
                    <td>
                      <button
                        className="button secondary compact"
                        onClick={() => setSelected(row.id)}
                      >
                        {uiText("View notice")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
      <Pagination
        previous={
          !invalid && pages.length && !records.loading
            ? () => {
                const prior = [...pages];
                setCursor(prior.pop() || null);
                setPages(prior);
              }
            : undefined
        }
        next={
          data?.next_cursor && !records.loading
            ? () => {
                setPages([...pages, cursor]);
                setCursor(data.next_cursor);
              }
            : undefined
        }
      />
      {create && (
        <CreateNotice
          key={path}
          path={path}
          matterId={matter.id}
          editable={editable}
          close={() => setCreate(false)}
          done={() => {
            setCreate(false);
            restart();
          }}
        />
      )}
      {selected && (
        <NoticeEditor
          key={`${path}:${selected}`}
          path={`${path}/${selected}`}
          matterId={matter.id}
          parentEditable={editable}
          holdState={data?.hold_state}
          close={() => setSelected(null)}
          changed={restart}
        />
      )}
    </Modal>
  );
}

function CreateNotice({
  path,
  matterId,
  editable,
  close,
  done,
}: {
  path: string;
  matterId: string;
  editable: boolean;
  close: () => void;
  done: () => void;
}) {
  const custodians = useResource<{
    items: { id: string; display_name: string }[];
  }>(`/cases/${matterId}/custodians`);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const dirty = useRef(false);
  const live = useMountedRef();
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current || !editable) return;
    const form = new FormData(event.currentTarget);
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await post(path, {
        custodian_id: form.get("custodian"),
        notice_text: form.get("text"),
        reason: form.get("reason"),
        next_reminder_date: form.get("next") || null,
      });
      if (live.current) done();
    } catch (failure) {
      if (live.current) setError(failure);
    } finally {
      busyRef.current = false;
      if (live.current) setBusy(false);
    }
  }
  return (
    <Modal
      title={uiText("Register notice")}
      close={() => {
        if (
          !busyRef.current &&
          (!dirty.current ||
            window.confirm(uiText("Discard unsaved notice changes?")))
        )
          close();
      }}
    >
      <p className="field-help">{uiText(manualMessage)}</p>
      <ErrorBox error={error || custodians.error} retry={custodians.refresh} />
      <form
        onSubmit={submit}
        onChange={() => {
          dirty.current = true;
        }}
      >
        <fieldset disabled={busy || !editable} className={styles.fields}>
          <label>
            {uiText("Custodian")}
            <select
              aria-label={uiText("Custodian")}
              name="custodian"
              required
              disabled={custodians.loading}
            >
              <option value="">{uiText("Select custodian")}</option>
              {custodians.data?.items.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.display_name}
                </option>
              ))}
            </select>
          </label>
          {custodians.data?.items.length === 0 && (
            <p className="field-help">
              {uiText(
                "Add a custodian in Sources & imports before registering a notice.",
              )}
            </p>
          )}
          <label>
            {uiText("Notice text")}
            <textarea
              aria-label={uiText("Notice text")}
              name="text"
              rows={8}
              required
              maxLength={20000}
            />
          </label>
          <label>
            {uiText("Reason")}
            <textarea
              aria-label={uiText("Reason")}
              name="reason"
              rows={2}
              required
              minLength={3}
              maxLength={2000}
            />
          </label>
          <label>
            {uiText("Next reminder date")}
            <input
              aria-label={uiText("Next reminder date")}
              name="next"
              type="date"
            />
          </label>
          <button
            className="button primary"
            disabled={!custodians.data?.items.length}
            type="submit"
          >
            {busy ? uiText("Saving…") : uiText("Register notice")}
          </button>
        </fieldset>
      </form>
    </Modal>
  );
}

function NoticeEditor({
  path,
  matterId,
  parentEditable,
  holdState,
  close,
  changed,
}: {
  path: string;
  matterId: string;
  parentEditable: boolean;
  holdState: string | undefined;
  close: () => void;
  changed: () => void;
}) {
  const detail = useResource<NoticeDetail>(path);
  const access = useResource<Matter>(`/cases/${matterId}`);
  const [base, setBase] = useState<NoticeDetail | null>(null);
  const [text, setText] = useState("");
  const [nextDate, setNextDate] = useState("");
  const [reason, setReason] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [message, setMessage] = useState<MessageKey | "">("");
  const live = useMountedRef();
  const busyRef = useRef(false);
  const current = detail.data;
  const dirty = Boolean(
    base &&
    (text !== base.notice_text || nextDate !== (base.next_reminder_date || "")),
  );
  const editable = Boolean(
    parentEditable &&
    current &&
    access.data &&
    current.hold_state === "active" &&
    !access.data.archived_at &&
    can(access.data.role, "hold"),
  );
  const outdated = Boolean(base && current && base.version !== current.version);
  useVisibleRefresh(detail.refresh);
  useVisibleRefresh(access.refresh);
  useEffect(() => {
    if (
      current &&
      (!base || (!dirty && !reason && !name && !busyRef.current && !conflict))
    ) {
      setBase(current);
      setText(current.notice_text);
      setNextDate(current.next_reminder_date || "");
    }
  }, [current, dirty, reason, name, conflict, base?.id]);

  function adopt(keep: boolean) {
    if (!current || !base || busyRef.current) return;
    const keepText =
      keep && text !== base.notice_text && current.state === "draft";
    const keepDate =
      keep &&
      nextDate !== (base.next_reminder_date || "") &&
      current.state !== "acknowledged";
    setText(keepText ? text : current.notice_text);
    setNextDate(keepDate ? nextDate : current.next_reminder_date || "");
    setBase(current);
    setConflict(false);
    setError(null);
    setMessage(
      keep
        ? "Your draft is preserved. Review the current values before saving again."
        : "Current notice loaded.",
    );
  }
  async function mutate(action: "save" | "issue" | "acknowledge" | "remind") {
    if (
      !current ||
      !base ||
      !editable ||
      busyRef.current ||
      outdated ||
      conflict ||
      reason.trim().length < 3
    )
      return;
    if (action !== "save" && dirty) return;
    const body: Record<string, unknown> = {
      expected_version: base.version,
      reason: reason.trim(),
    };
    if (action === "save") {
      if (current.state === "acknowledged" || !dirty) return;
      if (text !== base.notice_text) body.notice_text = text;
      if (nextDate !== (base.next_reminder_date || ""))
        body.next_reminder_date = nextDate || null;
    } else if (action === "acknowledge") {
      if (!name.trim() || current.state !== "issued") return;
      body.acknowledgement_name = name.trim();
    } else if (action === "issue" && current.state !== "draft") return;
    else if (action === "remind" && current.state !== "issued") return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const updated = await api<NoticeDetail>(
        action === "save" ? path : `${path}/${action}`,
        {
          method: action === "save" ? "PATCH" : "POST",
          body: JSON.stringify(body),
        },
      );
      if (!live.current) return;
      detail.setData((old) =>
        old && old.version > updated.version ? old : updated,
      );
      setBase(updated);
      setText(updated.notice_text);
      setNextDate(updated.next_reminder_date || "");
      setReason("");
      setName("");
      setConflict(false);
      setMessage("Notice record updated.");
      changed();
      historyVersion.current += 1;
      setHistoryKey(historyVersion.current);
    } catch (failure) {
      if (!live.current) return;
      setError(failure);
      if (failure instanceof ApiError && failure.status === 409) {
        setConflict(true);
        detail.refresh();
      } else if (
        failure instanceof ApiError &&
        [401, 403, 404].includes(failure.status)
      ) {
        detail.setData(null);
        detail.refresh();
        access.refresh();
      }
    } finally {
      busyRef.current = false;
      if (live.current) setBusy(false);
    }
  }
  const historyVersion = useRef(0);
  const [historyKey, setHistoryKey] = useState(0);
  const blocked = busy || !editable || outdated || conflict;
  return (
    <Modal
      title={uiText("Preservation notice")}
      wide
      close={() => {
        if (
          !busyRef.current &&
          (!(dirty || reason || name) ||
            window.confirm(uiText("Discard unsaved notice changes?")))
        )
          close();
      }}
    >
      <ErrorBox
        error={detail.error || access.error || error}
        retry={() => {
          detail.refresh();
          access.refresh();
        }}
      />
      {!current || !access.data ? (
        detail.loading || access.loading ? (
          <Loading />
        ) : null
      ) : (
        <>
          <div className={styles.heading}>
            <div>
              <h3>{current.custodian_name}</h3>
              <p className="field-help">
                {uiText(states[current.state])} ·{" "}
                {uiText("Version {0}", {
                  "0": base?.version || current.version,
                })}
              </p>
            </div>
            <button
              className="button secondary compact"
              disabled={busy}
              onClick={detail.refresh}
            >
              {uiText("Refresh")}
            </button>
          </div>
          <p className="notice subtle">{uiText(manualMessage)}</p>
          {(current.hold_state === "released" || holdState === "released") && (
            <p className="notice">
              {uiText(
                "This hold is released. Its notice register is read-only.",
              )}
            </p>
          )}
          {current.state !== "draft" && (
            <p className="field-help">
              {uiText(
                "Issued notice text and its hash are immutable. Acknowledgement is recorded by staff, not verified by the custodian.",
              )}
            </p>
          )}
          {(outdated || conflict) && (
            <section className="notice" role="status">
              <div>
                <p>
                  {uiText(
                    "This notice changed. Your draft is preserved; load the current version before saving.",
                  )}
                </p>
                <div className={styles.actions}>
                  <button
                    type="button"
                    className="button secondary compact"
                    disabled={busy || detail.loading}
                    onClick={() => adopt(false)}
                  >
                    {uiText("Load current notice")}
                  </button>
                  <button
                    type="button"
                    className="button secondary compact"
                    disabled={
                      busy || detail.loading || current.state !== base?.state
                    }
                    onClick={() => adopt(true)}
                  >
                    {uiText("Keep my changes with current version")}
                  </button>
                </div>
              </div>
            </section>
          )}
          {message && (
            <p className="notice success" role="status">
              {uiText(message)}
            </p>
          )}
          {base && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void mutate("save");
              }}
            >
              <fieldset className={styles.fields} disabled={busy || !editable}>
                <label>
                  {uiText("Notice text")}
                  <textarea
                    aria-label={uiText("Notice text")}
                    rows={9}
                    required
                    maxLength={20000}
                    value={text}
                    readOnly={current.state !== "draft"}
                    onChange={(event) => setText(event.target.value)}
                  />
                </label>
                <label>
                  {uiText("Next reminder date")}
                  <input
                    aria-label={uiText("Next reminder date")}
                    type="date"
                    value={nextDate}
                    readOnly={current.state === "acknowledged"}
                    onChange={(event) => setNextDate(event.target.value)}
                  />
                </label>
                {current.state !== "acknowledged" && (
                  <>
                    <label>
                      {uiText("Reason")}
                      <textarea
                        aria-label={uiText("Reason")}
                        rows={2}
                        required
                        minLength={3}
                        maxLength={2000}
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </label>
                    <div className={styles.actions}>
                      <button
                        className="button primary"
                        type="submit"
                        disabled={blocked || !dirty || reason.trim().length < 3}
                      >
                        {busy ? uiText("Saving…") : uiText("Save changes")}
                      </button>
                      {current.state === "draft" && (
                        <button
                          className="button secondary"
                          type="button"
                          disabled={
                            blocked || dirty || reason.trim().length < 3
                          }
                          onClick={() => void mutate("issue")}
                        >
                          {uiText("Record issuance")}
                        </button>
                      )}
                      {current.state === "issued" && (
                        <button
                          className="button secondary"
                          type="button"
                          disabled={
                            blocked || dirty || reason.trim().length < 3
                          }
                          onClick={() => void mutate("remind")}
                        >
                          {uiText("Record reminder")}
                        </button>
                      )}
                    </div>
                    {current.state === "issued" && (
                      <section className={styles.ack}>
                        <label>
                          {uiText("Acknowledgement name")}
                          <input
                            aria-label={uiText("Acknowledgement name")}
                            maxLength={200}
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                          />
                        </label>
                        <button
                          className="button secondary"
                          type="button"
                          disabled={
                            blocked ||
                            dirty ||
                            !name.trim() ||
                            reason.trim().length < 3
                          }
                          onClick={() => void mutate("acknowledge")}
                        >
                          {uiText("Record acknowledgement")}
                        </button>
                      </section>
                    )}
                    {dirty && (
                      <p className="field-help">
                        {uiText(
                          "Save or reload your changes before recording issuance, a reminder, or acknowledgement.",
                        )}
                      </p>
                    )}
                  </>
                )}
              </fieldset>
            </form>
          )}
          <dl className={styles.facts}>
            <div>
              <dt>{uiText("Created")}</dt>
              <dd>{date(current.created_at, true)}</dd>
            </div>
            <div>
              <dt>{uiText("Issued notice")}</dt>
              <dd>{date(current.issued_at, true)}</dd>
            </div>
            <div>
              <dt>{uiText("Acknowledged notice")}</dt>
              <dd>
                {date(current.acknowledged_at, true)}
                {current.acknowledgement_name && (
                  <span> · {current.acknowledgement_name}</span>
                )}
              </dd>
            </div>
            <div>
              <dt>{uiText("Recorded reminders")}</dt>
              <dd>
                {number(current.reminder_count)} ·{" "}
                {date(current.last_reminded_at, true)}
              </dd>
            </div>
          </dl>
          {base && text === base.notice_text && (
            <>
              <h4>{uiText("Notice text SHA-256")}</h4>
              <code className="hash-block">{base.notice_text_sha256}</code>
            </>
          )}
          <NoticeHistory key={historyKey} path={`${path}/history`} />
        </>
      )}
    </Modal>
  );
}

function NoticeHistory({ path }: { path: string }) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState<(string | null)[]>([]);
  const history = useResource<{
    items: {
      id: string;
      event_type: string;
      actor_id: string;
      created_at: string;
      version: number;
      reason: string;
    }[];
    next_cursor: string | null;
  }>(
    `${path}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  return (
    <section className={styles.history}>
      <h3>{uiText("Notice history")}</h3>
      <ErrorBox
        error={history.error}
        retry={() => {
          setCursor(null);
          setPages([]);
          history.refresh();
        }}
      />
      {history.loading && !history.data ? (
        <Loading />
      ) : (
        history.data?.items.map((event) => (
          <article key={event.id}>
            <strong>
              {Object.prototype.hasOwnProperty.call(
                historyLabels,
                event.event_type,
              )
                ? uiText(historyLabels[event.event_type])
                : event.event_type}{" "}
              · {uiText("Version {0}", { "0": event.version })}
            </strong>
            <p>{event.reason}</p>
            <small className="mono">
              {date(event.created_at, true)} · {event.actor_id}
            </small>
          </article>
        ))
      )}
      <Pagination
        previous={
          pages.length && !history.loading
            ? () => {
                const previous = [...pages];
                setCursor(previous.pop() || null);
                setPages(previous);
              }
            : undefined
        }
        next={
          history.data?.next_cursor && !history.loading
            ? () => {
                setPages([...pages, cursor]);
                setCursor(history.data!.next_cursor);
              }
            : undefined
        }
      />
    </section>
  );
}
