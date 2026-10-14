"use client";
import { uiText } from "@/lib/i18n";

import Link from "next/link";
import { useState } from "react";
import { date, uiLabel as label, number, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import { evidenceUrl } from "@/lib/search-scope";
import type { Evidence, Matter, Member, User } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";
import { EvidenceInspector } from "./explorer";

type Assignment = {
  id: string;
  title: string;
  state: string;
  version: number;
  assignee_id: string | null;
  assignee: { id: string; name: string; active: boolean } | null;
  counts: { total: number; reviewed: number; pending: number };
  reason: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  scope_type: "snapshot";
};

export default function ReviewQueue({
  matter,
  user,
}: {
  matter: Matter;
  user: User;
}) {
  const [mine, setMine] = useState(false),
    [openOnly, setOpenOnly] = useState(true),
    [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const rows = useResource<{ items: Assignment[]; next_cursor: string | null }>(
    `/cases/${matter.id}/assignments?mine=${mine}&open_only=${openOnly}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const [create, setCreate] = useState(false),
    [selected, setSelected] = useState<string | null>(null);
  const resetPages = () => {
    setCursor(null);
    setHistory([]);
  };
  return (
    <>
      <PageHeading
        eyebrow={uiText("HUMAN REVIEW WORKFLOW")}
        title={uiText("A clear next step.")}
        text={uiText(
          "Claim a fixed evidence snapshot, record human decisions and finish only when every allocated item has been reviewed.",
        )}
      >
        <Link
          className="button secondary"
          href={evidenceUrl(matter.id, {
            review_status: ["unreviewed", "needs_review"],
          })}
        >
          {uiText("Open all pending evidence")}
        </Link>
        <button
          className="button primary"
          disabled={!can(matter.role, "manage")}
          onClick={() => setCreate(true)}
        >
          <Icon name="plus" size={17} />
          {uiText("Create assignment")}
        </button>
      </PageHeading>
      <div className="queue-toolbar panel">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={mine}
            onChange={(event) => {
              setMine(event.target.checked);
              resetPages();
            }}
          />
          <span>{uiText("Assigned to me")}</span>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(event) => {
              setOpenOnly(event.target.checked);
              resetPages();
            }}
          />
          <span>{uiText("Open assignments only")}</span>
        </label>
        <button className="button secondary compact" onClick={rows.refresh}>
          {uiText("Refresh queue")}
        </button>
      </div>
      <ErrorBox error={rows.error} retry={rows.refresh} />
      {rows.loading ? (
        <Loading text={uiText("Opening allocated review snapshots…")} />
      ) : !rows.data?.items.length ? (
        <div className="panel">
          <Empty
            icon="review"
            title={uiText("No assignments in this scope")}
            text={uiText(
              "A matter lead or review manager can allocate selected evidence or an existing review set. Open pending evidence to inspect the unallocated backlog.",
            )}
          />
        </div>
      ) : (
        <div className="assignment-grid">
          {rows.data.items.map((row) => (
            <button
              className="panel assignment-card"
              key={row.id}
              onClick={() => setSelected(row.id)}
            >
              <div className="assignment-card-top">
                <Badge
                  value={row.state}
                  tone={
                    row.state === "completed"
                      ? "green"
                      : row.state === "cancelled"
                        ? "neutral"
                        : "amber"
                  }
                />
                <span className="muted">
                  {uiText("v{0}", { "0": row.version })}
                </span>
              </div>
              <h2>{row.title}</h2>
              <p>
                {row.assignee
                  ? `${row.assignee.name}${row.assignee.active ? "" : ` · ${uiText("Deactivated")}`}`
                  : uiText("Available to claim")}
              </p>
              <div className="review-progress-track">
                <span
                  style={{
                    width: `${row.counts.total ? (row.counts.reviewed / row.counts.total) * 100 : 0}%`,
                  }}
                />
              </div>
              <div className="assignment-card-bottom">
                <span>
                  {uiText("{0} of {1} human reviewed", {
                    "0": number(row.counts.reviewed),
                    "1": number(row.counts.total),
                  })}
                </span>
                <Icon name="arrow" size={17} />
              </div>
            </button>
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
          rows.data?.next_cursor
            ? () => {
                setHistory([...history, cursor]);
                setCursor(rows.data!.next_cursor);
              }
            : undefined
        }
      />
      {create && (
        <AssignmentCreateModal
          caseId={matter.id}
          close={() => setCreate(false)}
          done={() => {
            setCreate(false);
            rows.refresh();
          }}
        />
      )}
      {selected && (
        <AssignmentWorkspace
          matter={matter}
          user={user}
          id={selected}
          close={() => setSelected(null)}
          changed={rows.refresh}
        />
      )}
    </>
  );
}

export function AssignmentCreateModal({
  caseId,
  evidenceIds,
  close,
  done,
}: {
  caseId: string;
  evidenceIds?: string[];
  close: () => void;
  done: () => void;
}) {
  const members = useResource<{ items: Member[] }>(`/cases/${caseId}/members`),
    sets = useResource<{
      items: { id: string; name: string; count: number }[];
    }>(`/cases/${caseId}/review-sets`);
  const [scope, setScope] = useState(evidenceIds?.length ? "selection" : "set"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal title={uiText("Create a review assignment")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await post(`/cases/${caseId}/assignments`, {
              title: form.get("title"),
              reason: form.get("reason"),
              assignee_id: form.get("assignee_id") || null,
              ...(scope === "set"
                ? { review_set_id: form.get("review_set_id") }
                : {
                    evidence_ids:
                      evidenceIds ||
                      String(form.get("evidence_ids") || "")
                        .split(/[\s,]+/)
                        .filter(Boolean),
                  }),
            });
            done();
          } catch (error) {
            setError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorBox error={error || members.error || sets.error} />
        <label>
          {uiText("Assignment title")}
          <input name="title" required maxLength={200} />
        </label>
        <label>
          {uiText("Snapshot scope")}
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="set">{uiText("Existing review set")}</option>
            <option value="selection">
              {evidenceIds
                ? uiText("{0} selected evidence items", {
                    "0": number(evidenceIds.length),
                  })
                : uiText("Explicit evidence IDs")}
            </option>
          </select>
        </label>
        {scope === "set" ? (
          <label>
            {uiText("Review set")}
            <select name="review_set_id" required defaultValue="">
              <option value="" disabled>
                {uiText("Choose a saved snapshot")}
              </option>
              {sets.data?.items.map((set) => (
                <option
                  key={set.id}
                  value={set.id}
                  disabled={set.count > 500 || !set.count}
                >
                  {uiText("{0} · {1} items{2}", {
                    "0": set.name,
                    "1": number(set.count),
                    "2": set.count > 500 ? ` ${uiText("· exceeds limit")}` : "",
                  })}
                </option>
              ))}
            </select>
          </label>
        ) : evidenceIds ? (
          <p className="field-help">
            {uiText("{0} explicit items from your current page selection.", {
              "0": number(evidenceIds.length),
            })}
          </p>
        ) : (
          <label>
            {uiText("Evidence IDs")}
            <textarea
              name="evidence_ids"
              required
              rows={4}
              placeholder={uiText("One ID per line, or comma separated")}
            />
          </label>
        )}
        <label>
          {uiText("Assigned reviewer")}
          <select name="assignee_id" defaultValue="">
            <option value="">
              {uiText("Unassigned · eligible reviewers may claim")}
            </option>
            {members.data?.items
              .filter((member) => can(member.role, "review"))
              .map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.name} · {label(member.role)}
                </option>
              ))}
          </select>
        </label>
        <label>
          {uiText("Reason")}
          <textarea
            name="reason"
            required
            minLength={3}
            maxLength={2000}
            rows={3}
          />
        </label>
        <div className="notice subtle">
          <Icon name="lock" size={17} />
          <span>
            {uiText(
              "Assignments reserve up to 500 explicit evidence items. An item cannot belong to another open assignment. Counts track current human review decisions; privilege review remains separate.",
            )}
          </span>
        </div>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Allocating…") : uiText("Create assignment")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AssignmentWorkspace({
  matter,
  user,
  id,
  close,
  changed,
}: {
  matter: Matter;
  user: User;
  id: string;
  close: () => void;
  changed: () => void;
}) {
  const detail = useResource<Assignment>(
      `/cases/${matter.id}/assignments/${id}`,
    ),
    [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const items = useResource<{ items: Evidence[]; next_cursor: string | null }>(
    `/cases/${matter.id}/assignments/${id}/items${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const [action, setAction] = useState<string | null>(null),
    [evidence, setEvidence] = useState<string | null>(null);
  const row = detail.data,
    manager = can(matter.role, "manage"),
    owner = row?.assignee_id === user.id,
    closed = row && ["completed", "cancelled"].includes(row.state);
  const refresh = () => {
    detail.refresh();
    items.refresh();
    changed();
  };
  return (
    <Modal title={row?.title || uiText("Review assignment")} close={close} wide>
      <ErrorBox error={detail.error || items.error} retry={refresh} />
      {detail.loading || items.loading ? (
        <Loading />
      ) : (
        row && (
          <>
            <div className="assignment-detail-heading">
              <div>
                <Badge value={row.state} />
                <span className="muted">
                  {uiText("Snapshot · v{0}", { "0": row.version })}
                </span>
                <h3>{row.assignee?.name || uiText("Available to claim")}</h3>
                <p className="muted">
                  {uiText("{0} human reviewed · {1} pending · {2} allocated", {
                    "0": number(row.counts.reviewed),
                    "1": number(row.counts.pending),
                    "2": number(row.counts.total),
                  })}
                </p>
              </div>
              <div className="button-row">
                {!closed && (
                  <>
                    {row.state === "unassigned" &&
                      can(matter.role, "review") && (
                        <button
                          className="button primary compact"
                          onClick={() => setAction("claim")}
                        >
                          {uiText("Claim assignment")}
                        </button>
                      )}
                    {row.state === "assigned" && (owner || manager) && (
                      <>
                        <button
                          className="button secondary compact"
                          onClick={() => setAction("release")}
                        >
                          {uiText("Release allocation")}
                        </button>
                        <button
                          className="button primary compact"
                          disabled={row.counts.pending > 0}
                          onClick={() => setAction("complete")}
                        >
                          {uiText("Complete assignment")}
                        </button>
                      </>
                    )}
                    {manager && (
                      <button
                        className="button ghost compact danger-link"
                        onClick={() => setAction("cancel")}
                      >
                        {uiText("Cancel assignment")}
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
            <p className="field-help">
              {uiText("Created {0} · {1}", {
                "0": date(row.created_at, true),
                "1": row.reason,
              })}
            </p>
            <div
              className={`assignment-workbench ${evidence ? "has-inspector" : ""}`}
            >
              <div className="assignment-evidence-list">
                {items.data?.items.map((item) => (
                  <button
                    key={item.id}
                    className={`assignment-evidence ${evidence === item.id ? "selected" : ""}`}
                    onClick={() => setEvidence(item.id)}
                  >
                    <Icon
                      name={item.type === "email" ? "email" : "file"}
                      size={18}
                    />
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.sender || item.id}</small>
                    </span>
                    <Badge value={item.review_status} />
                  </button>
                ))}
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
                    items.data?.next_cursor
                      ? () => {
                          setHistory([...history, cursor]);
                          setCursor(items.data!.next_cursor);
                        }
                      : undefined
                  }
                />
              </div>
              {evidence && (
                <EvidenceInspector
                  caseId={matter.id}
                  id={evidence}
                  canReview={can(matter.role, "review")}
                  canPrivilege={can(matter.role, "privilege")}
                  canManage={manager}
                  close={() => setEvidence(null)}
                  changed={refresh}
                  open={setEvidence}
                />
              )}
            </div>
          </>
        )
      )}
      {action && row && (
        <AssignmentAction
          row={row}
          action={action}
          caseId={matter.id}
          close={() => setAction(null)}
          done={() => {
            setAction(null);
            refresh();
          }}
        />
      )}
    </Modal>
  );
}

function AssignmentAction({
  row,
  action,
  caseId,
  close,
  done,
}: {
  row: Assignment;
  action: string;
  caseId: string;
  close: () => void;
  done: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const actionTitle = uiText(
    action === "claim"
      ? "Claim assignment"
      : action === "complete"
        ? "Complete assignment"
        : action === "release"
          ? "Release allocation"
          : "Cancel assignment",
  );
  return (
    <Modal title={actionTitle} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await post(`/cases/${caseId}/assignments/${row.id}/${action}`, {
              expected_version: row.version,
              reason: form.get("reason"),
            });
            done();
          } catch (error) {
            setError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="muted">
          {action === "claim"
            ? uiText("Allocate this fixed snapshot to your review queue.")
            : action === "complete"
              ? uiText(
                  "Confirm the allocated items have received human review. This does not authorize export or determine privilege.",
                )
              : action === "release"
                ? uiText(
                    "Return this allocation to the unassigned queue. Existing review decisions are preserved.",
                  )
                : uiText(
                    "Close this allocation and release its reservation. Existing review decisions and assignment history are preserved.",
                  )}
        </p>
        <ErrorBox error={error} />
        <label>
          {uiText("Reason")}
          <input name="reason" required minLength={3} maxLength={2000} />
        </label>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Back")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Saving…") : actionTitle}
          </button>
        </div>
      </form>
    </Modal>
  );
}
