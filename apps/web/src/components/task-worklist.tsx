"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useResource } from "@/lib/hooks";
import { Badge, Empty, ErrorBox, Icon, Loading } from "./ui";
import styles from "./task-worklist.module.css";

type Task = {
  id: string;
  title: string;
  state: "open" | "in_progress";
  created_at: string;
  matter: { id: string; title: string; matter_number: string; role: string };
};
type WorkPage = {
  user_id: string;
  items: Task[];
  next_cursor: string | null;
  limit: number;
};

export default function MyWork({ userId }: { userId: string }) {
  return <Worklist key={userId} userId={userId} />;
}

function Worklist({ userId }: { userId: string }) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const resource = useResource<WorkPage>(
    "/worklist?limit=20" +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
  );
  const page = resource.data?.user_id === userId ? resource.data : null;
  const groups = useMemo(() => {
    const grouped = new Map<
      string,
      { matter: Task["matter"]; tasks: Task[] }
    >();
    for (const task of page?.items || []) {
      let group = grouped.get(task.matter.id);
      if (!group) {
        group = { matter: task.matter, tasks: [] };
        grouped.set(task.matter.id, group);
      }
      group.tasks.push(task);
    }
    return [...grouped.values()];
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

  return (
    <section
      className={`panel ${styles.panel}`}
      aria-labelledby="my-work-heading"
    >
      <div className={styles.heading}>
        <div>
          <span className="eyebrow">ASSIGNED TO YOU</span>
          <h2 id="my-work-heading">My work</h2>
          <p>
            Open tasks across your accessible, active matters. Updates while
            this page is visible.
          </p>
        </div>
        <button
          className="button secondary compact"
          type="button"
          onClick={resource.refresh}
          disabled={resource.loading}
        >
          Refresh my work
        </button>
      </div>
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading && !page ? (
        <Loading text="Loading your assigned work…" />
      ) : (
        <>
          {groups.map(({ matter, tasks }) => (
            <div className={styles.matter} key={matter.id}>
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
                    <span>{task.title}</span>
                    <Badge value={task.state} />
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
                  : "No open tasks assigned to you"
              }
              text={
                cursor
                  ? "Shared work may have changed. Return to the first page to see the current list."
                  : "Tasks assigned to you in active matters will appear here. Completed and cancelled tasks remain in their matter's task history."
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
    </section>
  );
}
