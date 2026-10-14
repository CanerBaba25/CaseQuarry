"use client";
import { uiText } from "@/lib/i18n";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, date, uiLabel as label, number, post } from "@/lib/api";
import { useMountedRef, useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Matter, Member } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";
import { TaskDeadline } from "./task-deadline";
import TaskDetails from "./task-details";
import {
  taskPriorities,
  taskPriorityTone,
  type TaskDetail,
  type TaskPriority,
} from "./task-types";
import deadlineStyles from "./task-deadline.module.css";

type Hold = {
  id: string;
  name: string;
  reason: string;
  state: string;
  created_by: string;
  released_by: string | null;
  created_at: string;
};
type Issue = {
  review?: {
    state: string;
    version: number;
    reviewed_by?: string;
    reason?: string;
    stale: boolean;
  };
  id: string;
  title: string;
  description: string;
  created_by: string;
  created_at: string;
};
type Task = {
  id: string;
  title: string;
  state: string;
  priority: TaskPriority;
  assigned_to: string | null;
  due_date: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  version: number;
};
type IssueEvidence = {
  id: string;
  evidence_id: string;
  title: string;
  side: string;
  note: string;
  created_by: string;
};
type Kind = "holds" | "issues" | "tasks";

export function GovernancePage({
  matter,
  kind,
}: {
  matter: Matter;
  kind: Kind;
}) {
  const viewRevision = useRef(0);
  const live = useMountedRef();
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const rawResource = useResource<{
    items: (Hold & Issue & Task)[];
    next_cursor: string | null;
    server_today?: string;
    time_zone?: string;
  }>(
    `/cases/${matter.id}/${kind}${kind === "tasks" ? "?limit=20" : ""}` +
      (cursor
        ? `${kind === "tasks" ? "&" : "?"}cursor=${encodeURIComponent(cursor)}`
        : ""),
  );
  const invalidTaskPage =
    kind === "tasks" &&
    rawResource.error instanceof ApiError &&
    ["TASK_LIST_CHANGED", "TASK_CURSOR_INVALID"].includes(
      rawResource.error.code,
    );
  const resource = {
    ...rawResource,
    data: invalidTaskPage ? null : rawResource.data,
    refresh: () => {
      viewRevision.current += 1;
      if (invalidTaskPage) {
        setCursor(null);
        setHistory([]);
      }
      rawResource.refresh();
    },
  };
  const [create, setCreate] = useState(false),
    [release, setRelease] = useState<Hold | null>(null),
    [issue, setIssue] = useState<Issue | null>(null),
    [deadlineTask, setDeadlineTask] = useState<Task | null>(null),
    [taskDetailsId, setTaskDetailsId] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const canManage = can(matter.role, "hold"),
    canReview = can(matter.role, "review");
  const canEditTask = canReview && !matter.archived_at;
  const members = useResource<{ items: Member[] }>(
    kind === "tasks" ? `/cases/${matter.id}/members` : null,
  );
  useEffect(() => {
    viewRevision.current += 1;
    setCursor(null);
    setHistory([]);
    setCreate(false);
    setRelease(null);
    setIssue(null);
    setDeadlineTask(null);
    setTaskDetailsId(null);
    setError(null);
  }, [matter.id, kind]);
  const copy = {
    holds: {
      eyebrow: uiText("PRESERVATION RECORDS"),
      title: uiText("Keep preservation visible."),
      text: uiText(
        "Track matter preservation requests and record releases. Active holds block matter archival.",
      ),
      add: uiText("Register hold"),
      empty: uiText("No preservation holds"),
      description: uiText(
        "Register a preservation request with a documented reason. This record does not deliver notices or replace counsel's preservation process.",
      ),
      icon: "lock",
    },
    issues: {
      eyebrow: uiText("THE ISSUE MATRIX"),
      title: uiText("Connect claims to the record."),
      text: uiText(
        "Organize supporting, contradictory and unclear evidence. Every interpretation remains a human decision.",
      ),
      add: uiText("Create issue"),
      empty: uiText("No issues defined"),
      description: uiText(
        "Create an issue, then link the evidence that supports it, contradicts it or leaves the question unresolved.",
      ),
      icon: "matters",
    },
    tasks: {
      eyebrow: uiText("TEAM WORK"),
      title: uiText("Move the review forward."),
      text: uiText(
        "Track the next steps in your investigation without losing their matter context.",
      ),
      add: uiText("Create task"),
      empty: uiText("No tasks yet"),
      description: uiText(
        "Record the next step for your matter. Task completion is separate from evidence review decisions.",
      ),
      icon: "review",
    },
  }[kind];
  function taskUpdated(
    updated: TaskDetail,
    submittedView = viewRevision.current,
  ) {
    if (!live.current) return;
    if (submittedView !== viewRevision.current) {
      rawResource.refresh();
      return;
    }
    resource.setData((current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === updated.id && item.version <= updated.version
                ? { ...item, ...updated }
                : item,
            ),
          }
        : current,
    );
    setCursor(null);
    setHistory([]);
    resource.refresh();
  }
  async function taskState(task: Task, state: string) {
    const submittedView = viewRevision.current;
    setBusy(true);
    setError(null);
    try {
      const updated = await api<TaskDetail>(
        `/cases/${matter.id}/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ state, expected_version: task.version }),
        },
      );
      taskUpdated(updated, submittedView);
    } catch (error) {
      if (live.current) {
        if (submittedView === viewRevision.current) setError(error);
        rawResource.refresh();
      }
    } finally {
      if (live.current) setBusy(false);
    }
  }
  async function taskAssignee(task: Task, assigned_to: string | null) {
    const submittedView = viewRevision.current;
    setBusy(true);
    setError(null);
    try {
      const updated = await api<TaskDetail>(
        `/cases/${matter.id}/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ assigned_to, expected_version: task.version }),
        },
      );
      taskUpdated(updated, submittedView);
    } catch (error) {
      if (live.current) {
        if (submittedView === viewRevision.current) setError(error);
        rawResource.refresh();
      }
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <>
      <PageHeading eyebrow={copy.eyebrow} title={copy.title} text={copy.text}>
        <button
          className="button primary"
          onClick={() => setCreate(true)}
          disabled={
            kind === "holds"
              ? !canManage
              : kind === "tasks"
                ? !canEditTask
                : !canReview
          }
        >
          <Icon name="plus" size={17} />
          {copy.add}
        </button>
      </PageHeading>
      {kind === "holds" && (
        <div className="notice amber">
          <Icon name="lock" size={18} />
          <span>
            {uiText(
              "These records track preservation decisions in CaseQuarry. Notice delivery, acknowledgments and legal sufficiency require your separate professional process.",
            )}
          </span>
        </div>
      )}
      <ErrorBox error={error} />
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : resource.error && !resource.data ? null : !resource.data?.items
          .length ? (
        <div className="panel">
          <Empty icon={copy.icon} title={copy.empty} text={copy.description} />
        </div>
      ) : kind === "issues" ? (
        <div className="issue-grid">
          {resource.data.items.map((item) => (
            <button
              className="panel issue-card"
              key={item.id}
              onClick={() => setIssue(item)}
            >
              <span className="eyebrow">{uiText("HUMAN-DEFINED ISSUE")}</span>
              {item.review && (
                <Badge
                  value={item.review.stale ? "Review stale" : item.review.state}
                  tone={item.review.stale ? "amber" : undefined}
                />
              )}
              <h2>{item.title}</h2>
              <p>
                {item.description ||
                  uiText(
                    "Open this issue to connect its supporting and contradictory sources.",
                  )}
              </p>
              <div>
                <small>
                  {uiText("Created {0}", { "0": date(item.created_at) })}
                </small>
                <span className="text-link">
                  {uiText("Open evidence matrix")}
                  <Icon name="arrow" size={16} />
                </span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>
                  {kind === "holds"
                    ? uiText("Preservation hold")
                    : uiText("Task")}
                </th>
                {kind === "tasks" && <th>{uiText("Priority")}</th>}
                <th>{uiText("Status")}</th>
                <th>{uiText("Created")}</th>
                {kind === "tasks" && <th>{uiText("Assigned to")}</th>}
                {kind === "tasks" && <th>{uiText("Due date")}</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {resource.data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    {kind === "tasks" ? (
                      <button
                        type="button"
                        className="text-link"
                        aria-label={uiText("Open task details: {0}", {
                          "0": item.title,
                        })}
                        onClick={() => setTaskDetailsId(item.id)}
                      >
                        <strong>{item.title}</strong>
                      </button>
                    ) : (
                      <strong>
                        {kind === "holds" ? item.name : item.title}
                      </strong>
                    )}
                    {kind === "holds" && (
                      <p className="table-description">{item.reason}</p>
                    )}
                  </td>
                  {kind === "tasks" && (
                    <td>
                      <Badge
                        value={`${item.priority} priority`}
                        tone={taskPriorityTone(item.priority)}
                      />
                    </td>
                  )}
                  <td>
                    <Badge
                      value={item.state}
                      tone={
                        item.state === "active"
                          ? "amber"
                          : item.state === "done"
                            ? "green"
                            : undefined
                      }
                    />
                  </td>
                  <td className="nowrap">{date(item.created_at)}</td>
                  {kind === "tasks" && (
                    <td>
                      <select
                        aria-label={uiText("Assigned to for {0}", {
                          "0": item.title,
                        })}
                        value={item.assigned_to || ""}
                        disabled={
                          busy ||
                          !canEditTask ||
                          members.loading ||
                          resource.loading
                        }
                        onChange={(event) =>
                          void taskAssignee(item, event.target.value || null)
                        }
                      >
                        <option value="">{uiText("Unassigned")}</option>
                        {item.assigned_to &&
                          !members.data?.items.some(
                            (member) => member.user_id === item.assigned_to,
                          ) && (
                            <option value={item.assigned_to} disabled>
                              {uiText("Unavailable assignee")}
                            </option>
                          )}
                        {members.data?.items.map((member) => (
                          <option
                            key={member.user_id}
                            value={member.user_id}
                            disabled={member.active === false}
                          >
                            {member.name}
                            {member.active === false
                              ? uiText("(inactive)")
                              : ""}
                          </option>
                        ))}
                      </select>
                    </td>
                  )}
                  {kind === "tasks" && (
                    <td>
                      <div className={deadlineStyles.cell}>
                        <TaskDeadline
                          value={item.due_date}
                          today={
                            resource.data!.server_today ||
                            new Date().toISOString().slice(0, 10)
                          }
                          complete={
                            !["open", "in_progress"].includes(item.state)
                          }
                        />
                        {canEditTask && (
                          <button
                            type="button"
                            className="text-link"
                            aria-label={uiText("Edit due date for {0}", {
                              "0": item.title,
                            })}
                            disabled={busy || resource.loading}
                            onClick={() => setDeadlineTask(item)}
                          >
                            {item.due_date
                              ? uiText("Change date")
                              : uiText("Set date")}
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                  <td>
                    {kind === "holds" ? (
                      item.state === "active" && (
                        <button
                          className="button secondary compact"
                          disabled={!canManage}
                          onClick={() => setRelease(item)}
                        >
                          {uiText("Record release")}
                        </button>
                      )
                    ) : (
                      <select
                        className="task-state"
                        aria-label={uiText("Status for {0}", {
                          "0": item.title,
                        })}
                        disabled={busy || !canEditTask || resource.loading}
                        value={item.state}
                        onChange={(event) =>
                          void taskState(item, event.target.value)
                        }
                      >
                        <option value="open">{uiText("Open (status)")}</option>
                        <option value="in_progress">
                          {uiText("In progress")}
                        </option>
                        <option value="done">{uiText("Done")}</option>
                        <option value="cancelled">{uiText("Cancelled")}</option>
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination
        text={
          resource.data?.items.length
            ? uiText("{0} records on this page", {
                "0": number(resource.data.items.length),
              })
            : undefined
        }
        previous={
          !invalidTaskPage && history.length
            ? () => {
                viewRevision.current += 1;
                const pages = [...history];
                setCursor(pages.pop() || null);
                setHistory(pages);
              }
            : undefined
        }
        next={
          !invalidTaskPage && resource.data?.next_cursor
            ? () => {
                viewRevision.current += 1;
                setHistory([...history, cursor]);
                setCursor(resource.data!.next_cursor);
              }
            : undefined
        }
      />
      {create && (
        <CreateGovernance
          kind={kind}
          matter={matter}
          close={() => setCreate(false)}
          done={() => {
            setCreate(false);
            setCursor(null);
            setHistory([]);
            resource.refresh();
          }}
        />
      )}
      {release && (
        <ReleaseHold
          matter={matter}
          hold={release}
          close={() => setRelease(null)}
          done={() => {
            setRelease(null);
            resource.refresh();
          }}
        />
      )}
      {deadlineTask && canEditTask && (
        <EditTaskDeadline
          matter={matter}
          task={deadlineTask}
          close={() => setDeadlineTask(null)}
          done={() => {
            setDeadlineTask(null);
            setCursor(null);
            setHistory([]);
            resource.refresh();
          }}
        />
      )}
      {taskDetailsId && (
        <TaskDetails
          matter={matter}
          taskId={taskDetailsId}
          close={() => setTaskDetailsId(null)}
          changed={taskUpdated}
        />
      )}
      {issue && (
        <IssueMatrix
          matter={matter}
          issue={issue}
          canReview={canReview}
          close={() => {
            setIssue(null);
            resource.refresh();
          }}
        />
      )}
    </>
  );
}

function CreateGovernance({
  kind,
  matter,
  close,
  done,
}: {
  kind: Kind;
  matter: Matter;
  close: () => void;
  done: () => void;
}) {
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const members = useResource<{ items: Member[] }>(
    kind === "tasks" ? `/cases/${matter.id}/members` : null,
  );
  return (
    <Modal
      title={
        kind === "holds"
          ? uiText("Register a preservation hold")
          : kind === "issues"
            ? uiText("Define an issue")
            : uiText("Create a matter task")
      }
      close={close}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await post(`/cases/${matter.id}/${kind}`, {
              ...Object.fromEntries(new FormData(event.currentTarget)),
              ...(kind === "tasks"
                ? {
                    assigned_to:
                      new FormData(event.currentTarget).get("assigned_to") ||
                      null,
                    due_date:
                      new FormData(event.currentTarget).get("due_date") || null,
                  }
                : {}),
            });
            if (live.current) done();
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <label>
          {kind === "holds" ? uiText("Hold name") : uiText("Title")}
          <input
            name={kind === "holds" ? "name" : "title"}
            required
            maxLength={kind === "holds" ? 200 : 300}
          />
        </label>
        {kind === "holds" ? (
          <>
            <label>
              {uiText("Preservation reason")}
              <textarea
                name="reason"
                required
                minLength={3}
                maxLength={2000}
                rows={4}
              />
            </label>
            <div className="notice amber">
              <Icon name="lock" size={18} />
              <span>
                {uiText(
                  "This hold becomes active immediately and blocks matter archival until an authorized release is recorded.",
                )}
              </span>
            </div>
          </>
        ) : kind === "issues" ? (
          <label>
            {uiText("Description")}
            <textarea
              name="description"
              maxLength={10000}
              rows={4}
              placeholder={uiText(
                "Describe the allegation or question to investigate",
              )}
            />
          </label>
        ) : (
          <>
            <label>
              {uiText("Task description")}
              <textarea
                name="description"
                rows={4}
                maxLength={10000}
                placeholder={uiText(
                  "Describe the next step, context or expected outcome",
                )}
              />
            </label>
            <label>
              {uiText("Task priority")}
              <select
                name="priority"
                aria-label={uiText("Task priority")}
                defaultValue="normal"
              >
                {taskPriorities.map((priority) => (
                  <option key={priority} value={priority}>
                    {label(priority)}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              {uiText(
                "Manual priorities help your team triage work. They do not calculate court deadlines or apply court rules.",
              )}
            </p>
            <label>
              {uiText("Due date")}
              <input
                name="due_date"
                type="date"
                max="9999-12-31"
                aria-label={uiText("Due date")}
                aria-describedby="create-task-date-hint"
              />
              <small id="create-task-date-hint" className={deadlineStyles.hint}>
                {uiText(
                  "Optional manual deadline. Your timezone controls dashboard date labels.",
                )}
              </small>
            </label>
            <label>
              {uiText("Assign task to")}
              <select name="assigned_to" defaultValue="">
                <option value="">{uiText("Unassigned")}</option>
                {members.data?.items
                  .filter((member) => member.active !== false)
                  .map((member) => (
                    <option key={member.user_id} value={member.user_id}>
                      {member.name}
                    </option>
                  ))}
              </select>
            </label>
            <ErrorBox error={members.error} />
            <p className="muted">
              {uiText(
                "New tasks start open. Task completion remains separate from evidence review decisions.",
              )}
            </p>
          </>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={busy}
          >
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Saving…") : uiText("Save record")}
            <Icon name="arrow" size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}

function EditTaskDeadline({
  matter,
  task,
  close,
  done,
}: {
  matter: Matter;
  task: Task;
  close: () => void;
  done: () => void;
}) {
  const [value, setValue] = useState(task.due_date || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const detail = useResource<TaskDetail>(
    `/cases/${matter.id}/tasks/${task.id}`,
  );
  const [expectedVersion, setExpectedVersion] = useState(task.version);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const changed = Boolean(
    detail.data && detail.data.version !== expectedVersion,
  );
  const denied =
    error instanceof ApiError && [401, 403, 404].includes(error.status);
  return (
    <Modal title={uiText("Update task deadline")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api(`/cases/${matter.id}/tasks/${task.id}`, {
              method: "PATCH",
              body: JSON.stringify({
                due_date: value || null,
                expected_version: expectedVersion,
              }),
            });
            if (live.current) done();
          } catch (error) {
            if (live.current) {
              setError(error);
              detail.refresh();
            }
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <p className={deadlineStyles.title}>{task.title}</p>
        <ErrorBox error={error} />
        <ErrorBox error={detail.error} retry={detail.refresh} />
        {changed && (
          <div className="notice amber">
            <span>
              {uiText(
                "This task changed while the dialog was open. Your date is preserved. Current deadline: {0}.",
                {
                  "0": detail.data!.due_date
                    ? date(detail.data!.due_date)
                    : uiText("No due date"),
                },
              )}
            </span>
            <button
              type="button"
              className="button secondary compact"
              onClick={() => {
                setExpectedVersion(detail.data!.version);
                setError(null);
              }}
            >
              {uiText("Keep date with current version")}
            </button>
          </div>
        )}
        <label>
          {uiText("Due date")}
          <input
            type="date"
            aria-label={uiText("Due date")}
            aria-describedby="edit-task-date-hint"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            max="9999-12-31"
            disabled={busy}
          />
          <small id="edit-task-date-hint" className={deadlineStyles.hint}>
            {uiText(
              "Leave empty to remove the deadline. Your timezone controls dashboard date labels.",
            )}
          </small>
        </label>
        <div className="form-actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={close}
          >
            {uiText("Cancel")}
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={
              busy || detail.loading || !detail.data || changed || denied
            }
          >
            {busy ? uiText("Saving…") : uiText("Save deadline")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ReleaseHold({
  matter,
  hold,
  close,
  done,
}: {
  matter: Matter;
  hold: Hold;
  close: () => void;
  done: () => void;
}) {
  const live = useMountedRef();
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <Modal title={uiText("Record a preservation release")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await post(`/cases/${matter.id}/holds/${hold.id}/release`, {
              reason: form.get("reason"),
            });
            if (live.current) done();
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <p className="muted">
          {uiText("You are recording a release for") + " "}
          <strong>{hold.name}</strong>
          {uiText(
            ". The audit record preserves who made this decision and why.",
          )}
        </p>
        <ErrorBox error={error} />
        <label>
          {uiText("Release reason")}
          <textarea
            name="reason"
            required
            minLength={3}
            maxLength={2000}
            rows={4}
          />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" required />
          <span>
            {uiText(
              "I have purpose-specific authority from counsel to release this preservation hold.",
            )}
          </span>
        </label>
        <div className="notice amber">
          <Icon name="alert" size={18} />
          <span>
            {uiText(
              "A released hold cannot be reactivated. A new preservation decision must be recorded as a new hold.",
            )}
          </span>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={busy}
          >
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Recording…") : uiText("Record authorized release")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function IssueMatrix({
  matter,
  issue,
  canReview,
  close,
}: {
  matter: Matter;
  issue: Issue;
  canReview: boolean;
  close: () => void;
}) {
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const detail = useResource<
    Issue & { evidence: IssueEvidence[]; next_cursor: string | null }
  >(
    `/cases/${matter.id}/issues/${issue.id}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <Modal title={issue.title} close={close} wide>
      <p className="muted">
        {issue.description ||
          uiText(
            "Connect the record to this issue through explicit reviewer interpretations.",
          )}
      </p>
      <ErrorBox error={detail.error} retry={detail.refresh} />
      <ErrorBox error={error} />
      {detail.data?.review && (
        <section className="panel issue-review-control">
          <div className="section-heading">
            <div>
              <h3>{uiText("Human issue review")}</h3>
              <Badge
                value={
                  detail.data.review.stale
                    ? "Review stale"
                    : detail.data.review.state
                }
                tone={detail.data.review.stale ? "amber" : undefined}
              />
            </div>
            <span className="muted">
              {uiText("v{0}", { "0": detail.data.review.version })}
            </span>
          </div>
          {detail.data.review.stale && (
            <div className="notice amber">
              {uiText(
                "Linked evidence or review changed after the last issue decision. Review the current scope again.",
              )}
            </div>
          )}
          {detail.data.review.reason && (
            <p className="muted">{detail.data.review.reason}</p>
          )}
          {canReview && (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                setBusy(true);
                setError(null);
                try {
                  await post(`/cases/${matter.id}/issues/${issue.id}/review`, {
                    state: form.get("state"),
                    reason: form.get("reason"),
                    expected_version: detail.data!.review!.version,
                  });
                  detail.refresh();
                } catch (error) {
                  setError(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                {uiText("Issue decision")}
                <select name="state" defaultValue="needs_review">
                  <option value="needs_review">{uiText("Needs review")}</option>
                  <option value="disputed">{uiText("Disputed")}</option>
                  <option
                    value="reviewed"
                    disabled={!can(matter.role, "privilege")}
                  >
                    {uiText("Reviewed by attorney or matter lead")}
                  </option>
                </select>
              </label>
              <label>
                {uiText("Issue review reason")}
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={2}
                />
              </label>
              <button className="button secondary compact" disabled={busy}>
                {uiText("Record issue decision")}
              </button>
            </form>
          )}
        </section>
      )}
      {detail.loading && !detail.data ? (
        <Loading />
      ) : (
        <div className="matrix-columns">
          {(
            [
              ["supports", "Supporting"],
              ["contradicts", "Contradictory"],
              ["unclear", "Unclear"],
            ] as const
          ).map(([side, text]) => (
            <section key={side} className={`matrix-column ${side}`}>
              <h3>{uiText(text)}</h3>
              {detail.data?.evidence
                .filter((item) => item.side === side)
                .map((item) => (
                  <Link
                    key={item.id}
                    href={`/app/matters/${matter.id}/evidence/${item.evidence_id}`}
                    className="matrix-evidence"
                    onClick={close}
                  >
                    <Icon name="file" size={16} />
                    <strong>{item.title}</strong>
                    <span className="mono">{item.evidence_id}</span>
                    {item.note && <p>{item.note}</p>}
                  </Link>
                ))}
              {!detail.data?.evidence.some((item) => item.side === side) && (
                <p className="muted">
                  {uiText("No linked evidence on this page.")}
                </p>
              )}
            </section>
          ))}
        </div>
      )}
      <Pagination
        previous={
          history.length
            ? () => {
                const pages = [...history];
                setCursor(pages.pop() || null);
                setHistory(pages);
              }
            : undefined
        }
        next={
          detail.data?.next_cursor
            ? () => {
                setHistory([...history, cursor]);
                setCursor(detail.data!.next_cursor);
              }
            : undefined
        }
      />
      {canReview && (
        <form
          className="issue-link-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const formElement = event.currentTarget;
            setBusy(true);
            setError(null);
            try {
              await post(
                `/cases/${matter.id}/issues/${issue.id}/evidence`,
                Object.fromEntries(new FormData(formElement)),
              );
              formElement.reset();
              detail.refresh();
            } catch (error) {
              setError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          <h3>{uiText("Link an evidence source")}</h3>
          <div className="form-grid">
            <label>
              {uiText("Evidence ID")}
              <input
                name="evidence_id"
                required
                placeholder={uiText(
                  "Copy the evidence ID from its source inspector",
                )}
              />
            </label>
            <label>
              {uiText("Relationship")}
              <select name="side">
                <option value="supports">{uiText("Supporting")}</option>
                <option value="contradicts">{uiText("Contradictory")}</option>
                <option value="unclear">{uiText("Unclear")}</option>
              </select>
            </label>
          </div>
          <label>
            {uiText("Interpretation note")}
            <textarea
              name="note"
              rows={2}
              maxLength={10000}
              placeholder={uiText(
                "Explain this human interpretation and any uncertainty",
              )}
            />
          </label>
          <button className="button primary compact" disabled={busy}>
            {busy ? uiText("Linking…") : uiText("Link evidence")}
            <Icon name="plus" size={15} />
          </button>
        </form>
      )}
    </Modal>
  );
}
