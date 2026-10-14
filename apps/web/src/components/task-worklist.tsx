"use client";
import { uiText, type MessageKey } from "@/lib/i18n";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useResource } from "@/lib/hooks";
import { api, ApiError, date, uiLabel as label, number } from "@/lib/api";
import { can } from "@/lib/permissions";
import { Badge, Empty, ErrorBox, Icon, Loading } from "./ui";
import { TaskDeadline } from "./task-deadline";
import TaskDetails from "./task-details";
import {
  taskPriorities,
  taskPriorityTone,
  type TaskDetail,
  type TaskPriority,
} from "./task-types";
import styles from "./task-worklist.module.css";

type Task = {
  id: string;
  title: string;
  state: "open" | "in_progress";
  priority: TaskPriority;
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
  q: string;
  priority: "all" | TaskPriority;
  sort: "due" | "priority";
  state_counts: { all: number; open: number; in_progress: number };
  priority_counts: Record<"all" | TaskPriority, number>;
  summary: { total: number; overdue: number; upcoming: number; no_due: number };
};
type DueFilter = "all" | "overdue" | "upcoming" | "no_due";
const filters: {
  value: DueFilter;
  label: MessageKey;
  count: keyof WorkPage["summary"];
  detail: MessageKey;
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
  const [priorityFilter, setPriorityFilter] =
    useState<WorkPage["priority"]>("all");
  const [sort, setSort] = useState<WorkPage["sort"]>("due");
  const [query, setQuery] = useState("");
  const [queryDraft, setQueryDraft] = useState("");
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [completing, setCompleting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const viewRevision = useRef(0);
  const live = useRef(true);
  const resource = useResource<WorkPage>(
    `/worklist?limit=20&due=${dueFilter}&state=${stateFilter}&priority=${priorityFilter}&sort=${sort}&q=${encodeURIComponent(query)}` +
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
    resource.data.state === stateFilter &&
    resource.data.priority === priorityFilter &&
    resource.data.sort === sort &&
    resource.data.q === query
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
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
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

  function changeView() {
    viewRevision.current += 1;
    setActionError(null);
  }
  function resetPage() {
    changeView();
    setCursor(null);
    setHistory([]);
  }

  async function complete(task: Task) {
    const submittedView = viewRevision.current;
    setCompleting(task.id);
    setActionError(null);
    try {
      await api(`/cases/${task.matter.id}/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ state: "done", expected_version: task.version }),
      });
    } catch (error) {
      if (live.current && submittedView === viewRevision.current)
        setActionError(error);
    } finally {
      if (live.current) {
        if (submittedView === viewRevision.current) {
          setCursor(null);
          setHistory([]);
        }
        resource.refresh();
        setCompleting(null);
      }
    }
  }
  function taskChanged(_task: TaskDetail) {
    resetPage();
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
          <span className="eyebrow">{uiText("ASSIGNED TO YOU")}</span>
          <h2 id="my-work-heading" tabIndex={-1}>
            {uiText("My work")}
          </h2>
          <p>
            {uiText(
              "Your open assignments across active matters, ordered by {0}.",
              {
                "0":
                  sort === "priority"
                    ? uiText("manual priority, then deadline")
                    : uiText("deadline"),
              },
            )}
          </p>
        </div>
        <button
          className="button secondary compact"
          type="button"
          onClick={() => {
            changeView();
            if (invalidPage) {
              setCursor(null);
              setHistory([]);
            }
            resource.refresh();
          }}
          disabled={resource.loading}
        >
          {uiText("Refresh my work")}
        </button>
      </div>
      <form
        className={styles.search}
        role="search"
        aria-label={uiText("Search your assigned tasks")}
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(queryDraft.trim());
          resetPage();
          resource.refresh();
        }}
      >
        <label>
          {uiText("Search task titles")}
          <input
            type="search"
            aria-label={uiText("Search task titles")}
            value={queryDraft}
            onChange={(event) => setQueryDraft(event.target.value)}
            maxLength={200}
            placeholder={uiText("Find an assigned task by its title")}
          />
        </label>
        <button type="submit" className="button secondary">
          <Icon name="search" size={16} /> {" " + uiText("Search tasks")}
        </button>
        {(query || queryDraft) && (
          <button
            type="button"
            className="button ghost"
            onClick={() => {
              setQuery("");
              setQueryDraft("");
              resetPage();
            }}
          >
            {uiText("Clear task search")}
          </button>
        )}
      </form>
      <div className={styles.statusBar}>
        <label>
          {uiText("Status")}
          <select
            aria-label={uiText("Task status filter")}
            value={stateFilter}
            onChange={(event) => {
              setStateFilter(event.target.value as WorkPage["state"]);
              resetPage();
            }}
          >
            <option value="all">
              {uiText("All open work{0}", {
                "0": page ? ` (${number(page.state_counts.all)})` : "",
              })}
            </option>
            <option value="open">
              {uiText("Open{0}", {
                "0": page ? ` (${number(page.state_counts.open)})` : "",
              })}
            </option>
            <option value="in_progress">
              {uiText("In progress{0}", {
                "0": page ? ` (${number(page.state_counts.in_progress)})` : "",
              })}
            </option>
          </select>
        </label>
        <label>
          {uiText("Priority")}
          <select
            aria-label={uiText("Task priority filter")}
            value={priorityFilter}
            onChange={(event) => {
              setPriorityFilter(event.target.value as WorkPage["priority"]);
              resetPage();
            }}
          >
            <option value="all">
              {uiText("All priorities{0}", {
                "0": page ? ` (${number(page.priority_counts.all)})` : "",
              })}
            </option>
            {taskPriorities.map((priority) => (
              <option key={priority} value={priority}>
                {label(priority)}
                {page ? ` (${number(page.priority_counts[priority])})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          {uiText("Sort by")}
          <select
            aria-label={uiText("Sort my work")}
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as WorkPage["sort"]);
              resetPage();
            }}
          >
            <option value="due">{uiText("Deadline first")}</option>
            <option value="priority">{uiText("Priority first")}</option>
          </select>
        </label>
      </div>
      <p className={styles.scope} role="status">
        {query ? (
          <>
            {uiText("Matching titles containing “")}
            {query}”.{" "}
          </>
        ) : null}
        {uiText(
          "Status counts cover matching active tasks; priority counts also reflect status. Deadline counts reflect title, status and priority. Priorities are manual and do not calculate court deadlines or apply court rules.",
        )}
      </p>
      <div
        className={styles.filters}
        aria-label={uiText("Filter assigned tasks by deadline")}
      >
        {filters.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={`${styles.filter} ${dueFilter === filter.value ? styles.selected : ""} ${filter.value === "overdue" ? styles.overdue : ""}`}
            aria-pressed={dueFilter === filter.value}
            title={uiText(filter.detail)}
            onClick={() => {
              setDueFilter(filter.value);
              resetPage();
            }}
          >
            <span>
              {filter.value === "all" && stateFilter !== "all"
                ? stateFilter === "open"
                  ? uiText("All open")
                  : uiText("All in progress")
                : uiText(filter.label)}
            </span>
            <strong>{page ? number(page.summary[filter.count]) : "—"}</strong>
          </button>
        ))}
      </div>
      {page && (
        <p className={styles.calendar}>
          {uiText("Calendar: {0} ({1}). Dates are entered by your team.", {
            "0": date(page.server_today),
            "1": page.time_zone,
          })}
        </p>
      )}
      <ErrorBox error={actionError} />
      <ErrorBox
        error={resource.error}
        retry={() => {
          changeView();
          if (invalidPage) {
            setCursor(null);
            setHistory([]);
          }
          resource.refresh();
        }}
      />
      {resource.loading && !page ? (
        <Loading text={uiText("Loading your assigned work…")} />
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
                        aria-label={uiText("Open task details: {0}", {
                          "0": task.title,
                        })}
                        onClick={() => setSelectedTask(task)}
                        className={styles.taskTitle}
                      >
                        {task.title}
                      </button>
                      <div className={styles.taskMeta}>
                        <Badge value={task.state} />
                        <Badge
                          value={`${task.priority} priority`}
                          tone={taskPriorityTone(task.priority)}
                        />
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
                        aria-label={uiText("Mark {0} complete", {
                          "0": task.title,
                        })}
                        disabled={Boolean(completing) || resource.loading}
                        onClick={() => void complete(task)}
                      >
                        <Icon name="check" size={15} />
                        {completing === task.id
                          ? uiText("Saving…")
                          : uiText("Complete")}
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
                query || priorityFilter !== "all" || stateFilter !== "all"
                  ? uiText("No assignments match these filters")
                  : cursor
                    ? uiText("No remaining tasks on this page")
                    : dueFilter === "all"
                      ? uiText("No open tasks assigned to you")
                      : uiText("No assignments match these filters")
              }
              text={
                query || priorityFilter !== "all" || stateFilter !== "all"
                  ? uiText(
                      "Try another title, priority or status, or clear the search to see your other assignments.",
                    )
                  : cursor
                    ? uiText(
                        "Shared work may have changed. Return to the first page to see the current list.",
                      )
                    : dueFilter === "all"
                      ? uiText(
                          "Tasks assigned to you in active matters will appear here. Change the status filter to see other active assignments. Completed and cancelled tasks remain in their matter's task history.",
                        )
                      : uiText(
                          "Choose another status or deadline filter to see your other assignments.",
                        )
              }
            />
          )}
          <div className={styles.footer}>
            <span>
              {page
                ? uiText("Tasks on this page: {0}", {
                    "0": number(page.items.length),
                  })
                : ""}
            </span>
            <div className={styles.pageActions}>
              {cursor && (
                <button
                  type="button"
                  className="text-link"
                  onClick={() => {
                    resetPage();
                  }}
                >
                  {uiText("First page")}
                </button>
              )}
              <button
                type="button"
                className="button secondary compact"
                aria-label={uiText("Previous page of my work")}
                disabled={!history.length || resource.loading}
                onClick={() => {
                  changeView();
                  const previous = [...history];
                  setCursor(previous.pop() || null);
                  setHistory(previous);
                }}
              >
                {uiText("Previous")}
              </button>
              <button
                type="button"
                className="button secondary compact"
                aria-label={uiText("Next page of my work")}
                disabled={!page?.next_cursor || resource.loading}
                onClick={() => {
                  if (page?.next_cursor) {
                    changeView();
                    setHistory([...history, cursor]);
                    setCursor(page.next_cursor);
                  }
                }}
              >
                {uiText("Next")}
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
