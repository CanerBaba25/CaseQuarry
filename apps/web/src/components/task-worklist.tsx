"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useResource } from "@/lib/hooks";
import { api, ApiError, date, number } from "@/lib/api";
import { can } from "@/lib/permissions";
import { Badge, Empty, ErrorBox, Icon, Loading } from "./ui";
import { TaskDeadline } from "./task-deadline";
import TaskDetails from "./task-details";
import type { TaskDetail } from "./task-types";
import styles from "./task-worklist.module.css";

type Task = {
  id: string;
  title: string;
  state: "open" | "in_progress";
  created_at: string;
  due_date: string | null;
  version: number;
  updated_at: string;
  matter: { id: string; title: string; matter_number: string; role: string };
};
type WorkPage = {
  user_id: string;
  items: Task[];
  next_cursor: string | null;
  limit: number;
  server_today: string;
  time_zone: string;
  state: "all" | "open" | "in_progress";
  state_counts: { all: number; open: number; in_progress: number };
  summary: { total: number; overdue: number; upcoming: number; no_due: number };
};
type DueFilter = "all" | "overdue" | "upcoming" | "no_due";
const filters: {
  value: DueFilter;
  label: string;
  count: keyof WorkPage["summary"];
  detail: string;
}[] = [
  {
    value: "all",
    label: "All open",
    count: "total",
    detail: "All open assignments",
  },
  {
    value: "overdue",
    label: "Overdue",
    count: "overdue",
    detail: "Due before today",
  },
  {
    value: "upcoming",
    label: "Next 7 days",
    count: "upcoming",
    detail: "Due today through the next seven days",
  },
  {
    value: "no_due",
    label: "No due date",
    count: "no_due",
    detail: "Assignments without a deadline",
  },
];

export default function MyWork({ userId }: { userId: string }) {
  return <Worklist key={userId} userId={userId} />;
}

function Worklist({ userId }: { userId: string }) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const [dueFilter, setDueFilter] = useState<DueFilter>("all");
  const [stateFilter, setStateFilter] = useState<WorkPage["state"]>("all");
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [completing, setCompleting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const resource = useResource<WorkPage>(
    `/worklist?limit=20&due=${dueFilter}&state=${stateFilter}` +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
  );
  const invalidPage =
    resource.error instanceof ApiError &&
    ["WORKLIST_CHANGED", "WORKLIST_CURSOR_INVALID"].includes(
      resource.error.code,
    );
  const page =
    !invalidPage &&
    resource.data?.user_id === userId &&
    resource.data.state === stateFilter
      ? resource.data
      : null;
  const groups = useMemo(() => {
    const grouped: { matter: Task["matter"]; tasks: Task[] }[] = [];
    for (const task of page?.items || []) {
      let group = grouped[grouped.length - 1];
      if (!group || group.matter.id !== task.matter.id) {
        group = { matter: task.matter, tasks: [] };
        grouped.push(group);
      }
      group.tasks.push(task);
    }
    return grouped;
  }, [page]);
  useEffect(() => {
    const refreshVisible = () => {
      if (document.visibilityState === "visible") resource.refresh();
    };
    const timer = setInterval(refreshVisible, 15000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [resource.refresh]);

  async function complete(task: Task) {
    setCompleting(task.id);
    setActionError(null);
    try {
      await api(`/cases/${task.matter.id}/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ state: "done", expected_version: task.version }),
      });
    } catch (error) {
      setActionError(error);
    } finally {
      setCursor(null);
      setHistory([]);
      resource.refresh();
      setCompleting(null);
    }
  }
  function taskChanged(_task: TaskDetail) {
    setCursor(null);
    setHistory([]);
    setActionError(null);
    resource.refresh();
  }
  function closeTask() {
    const taskId = selectedTask?.id;
    setSelectedTask(null);
    requestAnimationFrame(() => {
      const target =
        document.getElementById(`my-work-task-${taskId}`) ||
        document.getElementById("my-work-heading");
      target?.focus();
    });
  }

  return (
    <section
      className={`panel ${styles.panel}`}
      aria-labelledby="my-work-heading"
      aria-busy={resource.loading}
    >
      <div className={styles.heading}>
        <div>
          <span className="eyebrow">ASSIGNED TO YOU</span>
          <h2 id="my-work-heading" tabIndex={-1}>
            My work
          </h2>
          <p>
            Your open assignments, ordered by deadline, across active matters.
          </p>
        </div>
        <button
          className="button secondary compact"
          type="button"
          onClick={() => {
            if (invalidPage) {
              setCursor(null);
              setHistory([]);
            }
            resource.refresh();
          }}
          disabled={resource.loading}
        >
          Refresh my work
        </button>
      </div>
      <div className={styles.statusBar}>
        <label>
          Status
          <select
            aria-label="Task status filter"
            value={stateFilter}
            onChange={(event) => {
              setStateFilter(event.target.value as WorkPage["state"]);
              setCursor(null);
              setHistory([]);
              setActionError(null);
            }}
          >
            <option value="all">
              All open work{page ? ` (${number(page.state_counts.all)})` : ""}
            </option>
            <option value="open">
              Open{page ? ` (${number(page.state_counts.open)})` : ""}
            </option>
            <option value="in_progress">
              In progress
              {page ? ` (${number(page.state_counts.in_progress)})` : ""}
            </option>
          </select>
        </label>
        <p>
          Status counts include all your active assignments. Deadline counts
          reflect the selected status.
        </p>
      </div>
      <div
        className={styles.filters}
        aria-label="Filter assigned tasks by deadline"
      >
        {filters.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={`${styles.filter} ${dueFilter === filter.value ? styles.selected : ""} ${filter.value === "overdue" ? styles.overdue : ""}`}
            aria-pressed={dueFilter === filter.value}
            title={filter.detail}
            onClick={() => {
              setDueFilter(filter.value);
              setCursor(null);
              setHistory([]);
              setActionError(null);
            }}
          >
            <span>
              {filter.value === "all" && stateFilter !== "all"
                ? stateFilter === "open"
                  ? "All open"
                  : "All in progress"
                : filter.label}
            </span>
            <strong>{page ? number(page.summary[filter.count]) : "—"}</strong>
          </button>
        ))}
      </div>
      {page && (
        <p className={styles.calendar}>
          Calendar: {date(page.server_today)} ({page.time_zone}). Dates are
          entered by your team.
        </p>
      )}
      <ErrorBox error={actionError} />
      <ErrorBox
        error={resource.error}
        retry={() => {
          if (invalidPage) {
            setCursor(null);
            setHistory([]);
          }
          resource.refresh();
        }}
      />
      {resource.loading && !page ? (
        <Loading text="Loading your assigned work…" />
      ) : (
        <>
          {groups.map(({ matter, tasks }) => (
            <div className={styles.matter} key={`${matter.id}:${tasks[0].id}`}>
              <Link
                className={styles.matterLink}
                href={`/app/matters/${matter.id}/tasks`}
              >
                <Icon name="matters" size={17} />
                <span>
                  <small>{matter.matter_number}</small>
                  <strong>{matter.title}</strong>
                </span>
                <Icon name="chevron" size={14} />
              </Link>
              <ul className={styles.tasks}>
                {tasks.map((task) => (
                  <li key={task.id}>
                    <div className={styles.taskContent}>
                      <button
                        type="button"
                        id={`my-work-task-${task.id}`}
                        aria-label={`Open task details: ${task.title}`}
                        onClick={() => setSelectedTask(task)}
                        className={styles.taskTitle}
                      >
                        {task.title}
                      </button>
                      <div className={styles.taskMeta}>
                        <Badge value={task.state} />
                        <TaskDeadline
                          value={task.due_date}
                          today={page!.server_today}
                        />
                      </div>
                    </div>
                    {can(matter.role, "review") && (
                      <button
                        type="button"
                        className={`button secondary compact ${styles.complete}`}
                        aria-label={`Mark ${task.title} complete`}
                        disabled={Boolean(completing) || resource.loading}
                        onClick={() => void complete(task)}
                      >
                        <Icon name="check" size={15} />
                        {completing === task.id ? "Saving…" : "Complete"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {!groups.length && !resource.error && (
            <Empty
              icon="check"
              title={
                cursor
                  ? "No remaining tasks on this page"
                  : dueFilter === "all"
                    ? "No open tasks assigned to you"
                    : `No ${dueFilter === "no_due" ? "undated" : dueFilter === "upcoming" ? "upcoming" : "overdue"} assignments`
              }
              text={
                cursor
                  ? "Shared work may have changed. Return to the first page to see the current list."
                  : dueFilter === "all"
                    ? "Tasks assigned to you in active matters will appear here. Change the status filter to see other active assignments. Completed and cancelled tasks remain in their matter's task history."
                    : "Choose another status or deadline filter to see your other assignments."
              }
            />
          )}
          <div className={styles.footer}>
            <span>
              {page
                ? `${page.items.length} task${page.items.length === 1 ? "" : "s"} on this page`
                : ""}
            </span>
            <div className={styles.pageActions}>
              {cursor && (
                <button
                  type="button"
                  className="text-link"
                  onClick={() => {
                    setCursor(null);
                    setHistory([]);
                  }}
                >
                  First page
                </button>
              )}
              <button
                type="button"
                className="button secondary compact"
                aria-label="Previous page of my work"
                disabled={!history.length || resource.loading}
                onClick={() => {
                  const previous = [...history];
                  setCursor(previous.pop() || null);
                  setHistory(previous);
                }}
              >
                Previous
              </button>
              <button
                type="button"
                className="button secondary compact"
                aria-label="Next page of my work"
                disabled={!page?.next_cursor || resource.loading}
                onClick={() => {
                  if (page?.next_cursor) {
                    setHistory([...history, cursor]);
                    setCursor(page.next_cursor);
                  }
                }}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
      {selectedTask && (
        <TaskDetails
          matter={selectedTask.matter}
          taskId={selectedTask.id}
          close={closeTask}
          changed={taskChanged}
        />
      )}
    </section>
  );
}
