"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api, ApiError, date, getDisplayTimeZone, label } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Member } from "@/lib/types";
import { Badge, ErrorBox, Loading, Modal } from "./ui";
import { TaskDeadline } from "./task-deadline";
import type { TaskDetail, TaskMatter, TaskState } from "./task-types";
import styles from "./task-details.module.css";

type Draft = {
  title: string;
  description: string;
  state: TaskState;
  assigned_to: string;
  due_date: string;
};
const fields: (keyof Draft)[] = [
  "title",
  "description",
  "state",
  "assigned_to",
  "due_date",
];
const fieldNames: Record<keyof Draft, string> = {
  title: "Title",
  description: "Description",
  state: "Status",
  assigned_to: "Assignee",
  due_date: "Due date",
};
function toDraft(task: TaskDetail): Draft {
  return {
    title: task.title,
    description: task.description,
    state: task.state,
    assigned_to: task.assigned_to || "",
    due_date: task.due_date || "",
  };
}

type Props = {
  matter: TaskMatter;
  taskId: string;
  close: () => void;
  changed: (task: TaskDetail) => void;
};

export default function TaskDetails(props: Props) {
  return <TaskSession key={`${props.matter.id}:${props.taskId}`} {...props} />;
}

function TaskSession({ matter, taskId, close, changed }: Props) {
  const detail = useResource<TaskDetail>(`/cases/${matter.id}/tasks/${taskId}`);
  const access = useResource<TaskMatter>(`/cases/${matter.id}`);
  const members = useResource<{ items: Member[] }>(
    `/cases/${matter.id}/members`,
  );
  const [base, setBase] = useState<TaskDetail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const live = useRef(true);
  const id = useId();
  const record =
    detail.data?.id === taskId && detail.data.case_id === matter.id
      ? detail.data
      : null;
  const readable = Boolean(record && access.data?.id === matter.id);
  const editable =
    readable && can(access.data!.role, "review") && !access.data!.archived_at;
  const changedFields = useMemo(() => {
    if (!base || !draft) return [];
    const initial = toDraft(base);
    return fields.filter((field) => draft[field] !== initial[field]);
  }, [base, draft]);
  const dirty = changedFields.length > 0;
  const comparisonFields = useMemo(() => {
    if (!base || !record) return changedFields;
    const original = toDraft(base),
      current = toDraft(record);
    return fields.filter(
      (field) =>
        changedFields.includes(field) || original[field] !== current[field],
    );
  }, [base, record, changedFields]);
  const outdated = Boolean(base && record && base.version !== record.version);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (record && (!base || !dirty)) {
      setBase(record);
      setDraft(toDraft(record));
    }
  }, [record, dirty, base?.id]);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState !== "visible") return;
      detail.refresh();
      access.refresh();
      members.refresh();
    };
    const timer = setInterval(refresh, 15000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [detail.refresh, access.refresh, members.refresh]);

  function edit<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((current) => (current ? { ...current, [field]: value } : current));
    setMessage("");
  }
  function adoptLatest(keepChanges: boolean) {
    if (!record || !draft) return;
    const next = toDraft(record);
    if (keepChanges) {
      for (const field of changedFields) {
        Object.assign(next, { [field]: draft[field] });
      }
    }
    setBase(record);
    setDraft(next);
    setConflict(false);
    setError(null);
    setMessage(
      keepChanges
        ? "Your changed fields are retained against the current version. Review them, then save."
        : "Loaded the current task values.",
    );
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!base || !draft || !dirty || !editable || busy || outdated || conflict)
      return;
    const changes: Record<string, unknown> = { expected_version: base.version };
    for (const field of changedFields) {
      changes[field] =
        field === "assigned_to" || field === "due_date"
          ? draft[field] || null
          : field === "title"
            ? draft.title.trim()
            : draft[field];
    }
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const updated = await api<TaskDetail>(
        `/cases/${matter.id}/tasks/${taskId}`,
        {
          method: "PATCH",
          body: JSON.stringify(changes),
        },
      );
      if (!live.current) return;
      detail.setData((current) =>
        current &&
        current.id === updated.id &&
        current.version <= updated.version
          ? updated
          : current,
      );
      setBase(updated);
      setDraft(toDraft(updated));
      setConflict(false);
      setMessage("Task updated.");
      changed(updated);
    } catch (failure) {
      if (!live.current) return;
      setError(failure);
      if (
        failure instanceof ApiError &&
        ["TASK_VERSION_CONFLICT", "TASK_VERSION_REQUIRED"].includes(
          failure.code,
        )
      ) {
        setConflict(true);
        detail.refresh();
      } else if (
        failure instanceof ApiError &&
        [401, 403, 404].includes(failure.status)
      ) {
        detail.refresh();
        access.refresh();
      }
    } finally {
      if (live.current) setBusy(false);
    }
  }
  function showValue(field: keyof Draft, value: string) {
    if (field === "assigned_to")
      return value
        ? members.data?.items.find((member) => member.user_id === value)
            ?.name || "Unavailable assignee"
        : "Unassigned";
    if (field === "state") return label(value);
    if (field === "due_date") return value ? date(value) : "No due date";
    return value || "Empty";
  }

  return (
    <Modal title="Task details" close={close} wide>
      <ErrorBox error={detail.error} retry={detail.refresh} />
      <ErrorBox error={access.error} retry={access.refresh} />
      <ErrorBox error={error} />
      {!readable ? (
        detail.loading || access.loading ? (
          <Loading text="Loading task details…" />
        ) : null
      ) : (
        record && (
          <>
            <div className={styles.context}>
              <div className={styles.matter}>
                {access.data?.matter_number || matter.matter_number}
                <strong>{access.data?.title || matter.title}</strong>
              </div>
              <div className={styles.badges}>
                <Badge value={record.state} />
                <TaskDeadline
                  value={record.due_date}
                  today={record.server_today || ""}
                  complete={!["open", "in_progress"].includes(record.state)}
                />
              </div>
            </div>
            <dl className={styles.metadata}>
              <div>
                <dt>Created</dt>
                <dd>{date(record.created_at, true)}</dd>
              </div>
              <div>
                <dt>Last updated</dt>
                <dd>{date(record.updated_at, true)}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{record.version}</dd>
              </div>
            </dl>
            {!editable ? (
              <>
                <h3>{record.title}</h3>
                <p className={styles.description}>
                  {record.description || "No task description provided."}
                </p>
                <p className="notice subtle">
                  {access.data?.archived_at
                    ? "This matter is archived. Task details remain available for reading."
                    : "Your matter role allows reading this task. Editing requires review permission."}
                </p>
              </>
            ) : (
              draft &&
              base && (
                <form onSubmit={save}>
                  <label>
                    Task title
                    <input
                      value={draft.title}
                      onChange={(event) => edit("title", event.target.value)}
                      required
                      maxLength={300}
                      disabled={busy}
                    />
                  </label>
                  <label htmlFor={`${id}-description`}>
                    Task description
                    <textarea
                      id={`${id}-description`}
                      aria-label="Task description"
                      value={draft.description}
                      onChange={(event) =>
                        edit("description", event.target.value)
                      }
                      rows={4}
                      maxLength={10000}
                      disabled={busy}
                      placeholder="Describe the next step, context or expected outcome"
                    />
                  </label>
                  <div className={styles.fields}>
                    <label>
                      Task status
                      <select
                        aria-label="Task status"
                        value={draft.state}
                        onChange={(event) =>
                          edit("state", event.target.value as TaskState)
                        }
                        disabled={busy}
                      >
                        <option value="open">Open</option>
                        <option value="in_progress">In progress</option>
                        <option value="done">Done</option>
                        <option value="cancelled">Cancelled</option>
                      </select>
                    </label>
                    <label>
                      Task assignee
                      <select
                        aria-label="Task assignee"
                        value={draft.assigned_to}
                        onChange={(event) =>
                          edit("assigned_to", event.target.value)
                        }
                        disabled={
                          busy || members.loading || Boolean(members.error)
                        }
                      >
                        <option value="">Unassigned</option>
                        {draft.assigned_to &&
                          !members.data?.items.some(
                            (member) => member.user_id === draft.assigned_to,
                          ) && (
                            <option value={draft.assigned_to} disabled>
                              Unavailable assignee
                            </option>
                          )}
                        {members.data?.items.map((member) => (
                          <option
                            key={member.user_id}
                            value={member.user_id}
                            disabled={member.active === false}
                          >
                            {member.name}
                            {member.active === false ? " (inactive)" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Task due date
                      <input
                        aria-label="Task due date"
                        aria-describedby={`${id}-date-help`}
                        type="date"
                        value={draft.due_date}
                        max="9999-12-31"
                        disabled={busy}
                        onChange={(event) =>
                          edit("due_date", event.target.value)
                        }
                      />
                      <small id={`${id}-date-help`} className={styles.help}>
                        Optional calendar date entered by your team. Clear it to
                        remove the deadline.
                      </small>
                    </label>
                  </div>
                  <ErrorBox error={members.error} retry={members.refresh} />
                  {(outdated || conflict) && (
                    <section
                      className={styles.conflict}
                      aria-labelledby={`${id}-conflict-title`}
                    >
                      <h3 id={`${id}-conflict-title`}>
                        This task changed while you were editing.
                      </h3>
                      <p>
                        Your draft is preserved. Review the current values
                        before saving again.
                      </p>
                      {record.version !== base.version ? (
                        <>
                          <dl className={styles.comparison}>
                            {comparisonFields.map((field) => (
                              <div key={field}>
                                <dt>{fieldNames[field]}</dt>
                                <dd>
                                  <span>
                                    <small>Your draft</small>
                                    {showValue(field, draft[field])}
                                  </span>
                                  <span>
                                    <small>Current task</small>
                                    {showValue(field, toDraft(record)[field])}
                                  </span>
                                </dd>
                              </div>
                            ))}
                          </dl>
                          <div className={styles.actions}>
                            <button
                              type="button"
                              className="button secondary compact"
                              onClick={() => adoptLatest(false)}
                              disabled={busy}
                            >
                              Use latest task values
                            </button>
                            <button
                              type="button"
                              className="button secondary compact"
                              onClick={() => adoptLatest(true)}
                              disabled={busy}
                            >
                              Keep my changes with current version
                            </button>
                          </div>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="button secondary compact"
                          onClick={detail.refresh}
                          disabled={detail.loading}
                        >
                          Load current task
                        </button>
                      )}
                    </section>
                  )}
                  <p className={styles.help}>
                    Task completion is separate from evidence review. Timestamps
                    are displayed in {getDisplayTimeZone()}.
                  </p>
                  {message && (
                    <p role="status" className={styles.message}>
                      {message}
                    </p>
                  )}
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className="button secondary"
                      onClick={close}
                    >
                      Close
                    </button>
                    <button
                      type="submit"
                      className="button primary"
                      disabled={
                        busy ||
                        !dirty ||
                        !draft.title.trim() ||
                        outdated ||
                        conflict
                      }
                    >
                      {busy ? "Saving task…" : "Save task"}
                    </button>
                  </div>
                </form>
              )
            )}
          </>
        )
      )}
    </Modal>
  );
}
