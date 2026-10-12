"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, bytes, date, label, number, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type {
  Evidence,
  EvidenceDetail,
  Matter,
  SavedSearch,
  SearchResult,
  SearchSpec,
  Source,
  Span,
} from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { Pagination } from "./matter-pages";
import ThreadView from "./thread-view";

const statuses = ["unreviewed", "needs_review", "responsive", "non_responsive"];
const types = [
  "email",
  "pdf",
  "document",
  "text",
  "image",
  "spreadsheet",
  "container",
  "binary",
];
const defaultSpec: SearchSpec = {
  query: "",
  mode: "keyword",
  filters: {},
  sort: [{ field: "sent_at", order: "desc" }],
  group_by: null,
  page_size: 50,
  cursor: null,
};

export default function Explorer({
  matter,
  reviewOnly = false,
  emailOnly = false,
  evidenceId,
}: {
  matter: Matter;
  reviewOnly?: boolean;
  emailOnly?: boolean;
  evidenceId?: string;
}) {
  const router = useRouter();
  const [spec, setSpec] = useState<SearchSpec>(() => ({
    ...defaultSpec,
    filters: {
      ...(reviewOnly ? { review_status: ["unreviewed", "needs_review"] } : {}),
      ...(emailOnly ? { item_types: ["email"] } : {}),
    },
  }));
  const [draft, setDraft] = useState(""),
    [result, setResult] = useState<SearchResult | null>(null),
    [error, setError] = useState<unknown>(null),
    [loading, setLoading] = useState(true),
    [version, setVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(
      evidenceId || null,
    ),
    [selected, setSelected] = useState<string[]>([]),
    [history, setHistory] = useState<(string | null)[]>([]),
    [filtersOpen, setFiltersOpen] = useState(false);
  const [dialog, setDialog] = useState<
    "saved" | "set" | "bulk" | "export" | null
  >(null);
  const sources = useResource<{ items: Source[] }>(
      `/cases/${matter.id}/sources`,
    ),
    saved = useResource<{ items: SavedSearch[] }>(
      `/cases/${matter.id}/saved-searches`,
    );
  const person = useResource<{ email: string; name: string }>(
    spec.filters.person_id
      ? `/cases/${matter.id}/people/${spec.filters.person_id}`
      : null,
  );
  const canReview = can(matter.role, "review");
  const canPrivilege = can(matter.role, "privilege");
  const canExport = can(matter.role, "export");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const query = params.get("q") || "",
      type = params.get("type"),
      participant = params.get("person_id");
    setDraft(query);
    setHistory([]);
    setSelected([]);
    setSelectedId(evidenceId || null);
    setSpec({
      ...defaultSpec,
      query,
      filters: {
        ...(participant ? { person_id: participant } : {}),
        ...(reviewOnly
          ? { review_status: ["unreviewed", "needs_review"] }
          : {}),
        ...(type
          ? { item_types: [type] }
          : emailOnly
            ? { item_types: ["email"] }
            : {}),
      },
    });
  }, [matter.id, reviewOnly, emailOnly, evidenceId]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    post<SearchResult>(`/cases/${matter.id}/search`, spec, controller.signal)
      .then(setResult)
      .catch((error) => {
        if (!controller.signal.aborted) setError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [matter.id, spec, version]);
  function update(changes: Partial<SearchSpec>) {
    setSpec((current) => ({ ...current, ...changes, cursor: null }));
    setHistory([]);
    setSelected([]);
  }
  function filter(key: string, value: unknown) {
    const filters = { ...spec.filters };
    if (
      value === null ||
      value === "" ||
      (Array.isArray(value) && value.length === 0) ||
      value === false
    )
      delete filters[key];
    else filters[key] = value;
    update({ filters });
  }
  function toggle(key: string, value: string) {
    const current = (spec.filters[key] || []) as string[];
    filter(
      key,
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  }
  const activeFilters = Object.entries(spec.filters).flatMap(([key, value]) =>
    (Array.isArray(value) ? value : [value]).map((item) => ({
      key,
      value: item,
    })),
  );
  const allVisibleSelected = Boolean(
    result?.items.length &&
    result.items.every((item) => selected.includes(item.evidence_id)),
  );
  const groupField = (
    {
      type: "item_types",
      sender: "sender",
      source: "source_ids",
      review_status: "review_status",
      month: "month",
      thread: "thread_id",
    } as Record<string, string>
  )[spec.group_by || ""];
  return (
    <div className="explorer-shell">
      <div className="explorer-heading">
        <div>
          <span className="eyebrow">
            {matter.matter_number} ·{" "}
            {reviewOnly ? "HUMAN REVIEW" : "THE EVIDENCE RECORD"}
          </span>
          <h1>{reviewOnly ? "Review queue" : "Evidence explorer"}</h1>
        </div>
        <div className="explorer-heading-actions">
          <button
            className="button secondary compact"
            onClick={() => setDialog("saved")}
          >
            <Icon name="star" size={16} />
            Save search
          </button>
          <Link
            href={`/app/matters/${matter.id}/sources`}
            className="button primary compact"
          >
            <Icon name="upload" size={16} />
            Import
          </Link>
        </div>
      </div>
      <form
        className="query-bar"
        onSubmit={(event) => {
          event.preventDefault();
          update({ query: draft });
        }}
      >
        <Icon name="search" size={21} />
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={'Search evidence… e.g. "payment approved" AND invoice'}
          aria-label="Search evidence"
        />
        <button
          type="submit"
          className="button primary compact"
          aria-disabled={!can(matter.role, "import")}
          tabIndex={can(matter.role, "import") ? undefined : -1}
          onClick={(event) => {
            if (!can(matter.role, "import")) event.preventDefault();
          }}
          disabled={loading}
        >
          Search
          <Icon name="arrow" size={16} />
        </button>
      </form>
      <div className="explorer-toolbar">
        <button
          className={`button secondary compact filter-toggle ${activeFilters.length ? "selected" : ""}`}
          onClick={() => setFiltersOpen((value) => !value)}
        >
          <Icon name="filter" size={15} />
          Filters{activeFilters.length ? ` (${activeFilters.length})` : ""}
        </button>
        <div className="results-label" role="status">
          {loading
            ? "Searching…"
            : `${number(result?.total_hits)} ${result?.total_hits === 1 ? "result" : "results"}`}
          <span>Keyword search · This matter</span>
        </div>
        <div className="toolbar-selects">
          <label>
            Sort
            <select
              aria-label="Sort evidence"
              value={`${spec.sort[0].field}:${spec.sort[0].order}`}
              onChange={(event) => {
                const [field, order] = event.target.value.split(":");
                update({ sort: [{ field, order }] });
              }}
            >
              <option value="sent_at:desc">Newest first</option>
              <option value="sent_at:asc">Oldest first</option>
              <option value="title:asc">Title A–Z</option>
              <option value="size:desc">Largest first</option>
              <option value="evidence_id:asc">Evidence ID</option>
            </select>
          </label>
          <label>
            Group
            <select
              aria-label="Group evidence"
              value={spec.group_by || ""}
              onChange={(event) =>
                update({ group_by: event.target.value || null })
              }
            >
              <option value="">No grouping</option>
              <option value="sender">Sender</option>
              <option value="month">Month</option>
              <option value="type">File type</option>
              <option value="source">Source</option>
              <option value="review_status">Review status</option>
              <option value="thread">Thread</option>
            </select>
          </label>
          <button
            className="button secondary compact"
            onClick={() => setDialog("export")}
            disabled={!canExport}
          >
            <Icon name="export" size={15} />
            Export
          </button>
        </div>
      </div>
      {activeFilters.length > 0 && (
        <div className="filter-chips">
          {activeFilters.map((item) => (
            <button
              key={`${item.key}-${item.value}`}
              onClick={() => {
                const current = spec.filters[item.key];
                filter(
                  item.key,
                  Array.isArray(current)
                    ? current.filter((value) => value !== item.value)
                    : null,
                );
              }}
            >
              <span>
                {item.key === "person_id" ? "Participant" : label(item.key)}:{" "}
                {typeof item.value === "boolean"
                  ? "Yes"
                  : item.key === "person_id"
                    ? person.data?.name ||
                      person.data?.email ||
                      "Selected header address"
                    : label(String(item.value))}
              </span>
              <Icon name="close" size={12} />
            </button>
          ))}
          <button
            className="clear-filters"
            onClick={() => update({ filters: {} })}
          >
            Clear filters
          </button>
        </div>
      )}
      <ErrorBox error={error} retry={() => setVersion((value) => value + 1)} />
      <div
        className={`evidence-workbench ${selectedId ? "has-inspector" : ""}`}
      >
        <aside
          className={`filter-panel ${filtersOpen ? "open" : ""}`}
          aria-label="Evidence filters"
        >
          <div className="filter-title">
            <strong>Refine the record</strong>
            <Icon name="filter" size={16} />
          </div>
          <FilterSection title="Evidence type">
            {types.map((type) => {
              const bucket = result?.facets
                .find((item) =>
                  ["type", "item_type", "item_types"].includes(item.field),
                )
                ?.values.find((item) => item.key === type);
              return (
                <label className="facet-option" key={type}>
                  <input
                    type="checkbox"
                    checked={(
                      (spec.filters.item_types || []) as string[]
                    ).includes(type)}
                    onChange={() => toggle("item_types", type)}
                  />
                  <Icon name={type === "email" ? "email" : "file"} size={15} />
                  <span>
                    {type === "container"
                      ? "Archive / mailbox"
                      : type === "binary"
                        ? "Other / unsupported"
                        : label(type)}
                  </span>
                  {bucket && <small>{number(bucket.count)}</small>}
                </label>
              );
            })}
          </FilterSection>
          <FilterSection title="Review status">
            {statuses.map((status) => (
              <label className="facet-option" key={status}>
                <input
                  type="checkbox"
                  checked={(
                    (spec.filters.review_status || []) as string[]
                  ).includes(status)}
                  onChange={() => toggle("review_status", status)}
                />
                <span>{label(status)}</span>
                {result?.facets
                  .find((item) => item.field === "review_status")
                  ?.values.find((item) => item.key === status) && (
                  <small>
                    {number(
                      result.facets
                        .find((item) => item.field === "review_status")
                        ?.values.find((item) => item.key === status)?.count,
                    )}
                  </small>
                )}
              </label>
            ))}
          </FilterSection>
          <FilterSection title="Collection">
            <label className="filter-field">
              Source
              <select
                value={((spec.filters.source_ids || []) as string[])[0] || ""}
                onChange={(event) =>
                  filter(
                    "source_ids",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">All sources</option>
                {sources.data?.items.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              Sender
              <input
                value={String(spec.filters.sender || "")}
                onChange={(event) => filter("sender", event.target.value)}
                placeholder="Email address"
              />
            </label>
            <label className="facet-option">
              <input
                type="checkbox"
                checked={Boolean(spec.filters.has_attachment)}
                onChange={(event) =>
                  filter("has_attachment", event.target.checked)
                }
              />
              <span>With attachments</span>
            </label>
          </FilterSection>
          <FilterSection title="Date · UTC">
            <label className="filter-field">
              From
              <input
                type="date"
                value={String(spec.filters.date_from || "")}
                onChange={(event) => filter("date_from", event.target.value)}
              />
            </label>
            <label className="filter-field">
              To
              <input
                type="date"
                value={String(spec.filters.date_to || "")}
                onChange={(event) => filter("date_to", event.target.value)}
              />
            </label>
          </FilterSection>
          <FilterSection title="Saved searches">
            {saved.data?.items.length ? (
              <select
                aria-label="Load saved search"
                value=""
                onChange={(event) => {
                  const item = saved.data?.items.find(
                    (item) => item.id === event.target.value,
                  );
                  if (item) {
                    update({ ...item.query_spec, cursor: null });
                    setDraft(item.query_spec.query);
                  }
                }}
              >
                <option value="">Choose a saved search</option>
                {saved.data.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            ) : (
              <p className="muted">Save a query to return to it later.</p>
            )}
            <ErrorBox error={saved.error} />
          </FilterSection>
          <div className="filter-footnote">
            <Icon name="shield" size={16} />
            <p>
              Search is limited to the evidence you can access in this matter.
            </p>
          </div>
        </aside>
        <section className="results-panel" aria-label="Search results">
          {spec.group_by && result?.groups.length ? (
            <div className="group-summary">
              <div>
                <strong>{label(spec.group_by)} groups</strong>
                <small>Counts across the full matching scope</small>
              </div>
              <div className="group-chips">
                {result.groups.map((item) => (
                  <button
                    key={item.key}
                    disabled={!item.key || item.key === "Unknown"}
                    title={
                      !item.key || item.key === "Unknown"
                        ? "Missing metadata cannot be drilled down in this preview. These items remain in the evidence results."
                        : undefined
                    }
                    onClick={() => {
                      if (spec.group_by === "month") {
                        const first = `${item.key}-01`;
                        const lastDate = new Date(`${first}T00:00:00Z`);
                        if (!Number.isNaN(lastDate.getTime())) {
                          lastDate.setUTCMonth(lastDate.getUTCMonth() + 1);
                          lastDate.setUTCDate(0);
                          update({
                            filters: {
                              ...spec.filters,
                              date_from: first,
                              date_to: lastDate.toISOString().slice(0, 10),
                            },
                          });
                        }
                      } else
                        filter(
                          groupField,
                          ["sender", "thread_id"].includes(groupField)
                            ? item.key
                            : [item.key],
                        );
                    }}
                  >
                    <span>{item.key === "" ? "Not recorded" : item.key}</span>
                    <strong>{number(item.count)}</strong>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {selected.length > 0 && (
            <div className="selection-toolbar">
              <span>
                <strong>{number(selected.length)}</strong> selected on this page
              </span>
              <div>
                <button
                  className="button secondary compact"
                  disabled={!canReview}
                  onClick={() => setDialog("bulk")}
                >
                  Review selected
                </button>
                <button
                  className="button secondary compact"
                  onClick={() => setDialog("set")}
                  disabled={!canReview}
                >
                  Save review set
                </button>
                <button
                  className="icon-button"
                  aria-label="Clear selection"
                  onClick={() => setSelected([])}
                >
                  <Icon name="close" size={15} />
                </button>
              </div>
            </div>
          )}
          <div className={`evidence-table-wrap ${loading ? "is-loading" : ""}`}>
            {loading && !result ? (
              <Loading text="Searching the evidence record…" />
            ) : !result?.items.length ? (
              <Empty
                icon="search"
                title={
                  spec.query || activeFilters.length
                    ? "No evidence matches this scope"
                    : "Your record is ready to begin"
                }
                text={
                  spec.query || activeFilters.length
                    ? "Try a different query or widen your filters. Unprocessed sources remain in the import report."
                    : "Import a source to preserve originals and make their extracted content searchable."
                }
              >
                {!spec.query && !activeFilters.length && (
                  <Link
                    className="button primary"
                    href={`/app/matters/${matter.id}/sources`}
                  >
                    Import evidence
                    <Icon name="arrow" size={16} />
                  </Link>
                )}
              </Empty>
            ) : (
              <table className="evidence-table">
                <thead>
                  <tr>
                    <th className="checkbox-cell">
                      <input
                        type="checkbox"
                        aria-label="Select all visible evidence"
                        checked={allVisibleSelected}
                        onChange={() =>
                          setSelected(
                            allVisibleSelected
                              ? []
                              : result.items.map((item) => item.evidence_id),
                          )
                        }
                      />
                    </th>
                    <th>Evidence</th>
                    <th>Date · UTC</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((item) => (
                    <tr
                      className={
                        selectedId === item.evidence_id ? "selected-row" : ""
                      }
                      key={item.evidence_id}
                    >
                      <td className="checkbox-cell">
                        <input
                          type="checkbox"
                          aria-label={`Select ${item.title}`}
                          checked={selected.includes(item.evidence_id)}
                          onChange={() =>
                            setSelected((current) =>
                              current.includes(item.evidence_id)
                                ? current.filter(
                                    (id) => id !== item.evidence_id,
                                  )
                                : [...current, item.evidence_id],
                            )
                          }
                        />
                      </td>
                      <td>
                        <button
                          className="evidence-open"
                          onClick={() => setSelectedId(item.evidence_id)}
                        >
                          <span className={`evidence-kind ${item.type}`}>
                            <Icon
                              name={item.type === "email" ? "email" : "file"}
                              size={18}
                            />
                          </span>
                          <span>
                            <strong>{item.title || item.evidence_id}</strong>
                            <span className="evidence-subtitle">
                              {item.sender || label(item.type)}
                              {item.has_attachments && (
                                <span className="attachment-indicator">
                                  <Icon name="file" size={12} />
                                  Attachments
                                </span>
                              )}
                            </span>
                            <span className="evidence-snippet">
                              {item.snippet || "No text snippet available"}
                            </span>
                            <span className="evidence-id mono">
                              {item.evidence_id}
                            </span>
                          </span>
                        </button>
                      </td>
                      <td className="evidence-date">{date(item.date_utc)}</td>
                      <td>
                        <Badge value={item.review_status} />
                        {item.privilege_status &&
                          item.privilege_status !== "none" && (
                            <Badge
                              value={`Privilege ${item.privilege_status}`}
                              tone={
                                item.privilege_status === "confirmed"
                                  ? "red"
                                  : "amber"
                              }
                            />
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <Pagination
            text={
              result?.items.length
                ? `Page ${history.length + 1} · ${number(result.items.length)} shown of ${number(result.total_hits)}`
                : undefined
            }
            previous={
              history.length && !loading
                ? () => {
                    const pages = [...history];
                    const cursor = pages.pop() || null;
                    setHistory(pages);
                    setSelected([]);
                    setSpec((current) => ({ ...current, cursor }));
                  }
                : undefined
            }
            next={
              result?.next_cursor && !loading
                ? () => {
                    setHistory([...history, spec.cursor]);
                    setSelected([]);
                    setSpec((current) => ({
                      ...current,
                      cursor: result.next_cursor,
                    }));
                  }
                : undefined
            }
          />
          {result?.coverage && (
            <div className="results-coverage">
              <Icon name="alert" size={14} />
              <span>
                {Object.entries(result.coverage.states || {})
                  .filter(([key]) =>
                    [
                      "pending",
                      "failed",
                      "unsupported",
                      "partial",
                      "locked",
                      "quarantined",
                    ].includes(key),
                  )
                  .map(
                    ([key, count]) =>
                      `${number(count)} ${label(key).toLowerCase()}`,
                  )
                  .join(" · ") ||
                  "See source inventory for full processing coverage."}
              </span>
            </div>
          )}
        </section>
        {selectedId ? (
          <EvidenceInspector
            caseId={matter.id}
            id={selectedId}
            canReview={canReview}
            canPrivilege={canPrivilege}
            close={() => {
              setSelectedId(null);
              if (evidenceId) router.push(`/app/matters/${matter.id}/explorer`);
            }}
            changed={() => setVersion((value) => value + 1)}
            open={setSelectedId}
          />
        ) : (
          <aside className="inspector-placeholder">
            <span className="empty-icon">
              <Icon name="file" size={25} />
            </span>
            <h3>Read the record.</h3>
            <p>
              Open an evidence item to inspect its source, extracted text and
              review history.
            </p>
            <div>
              <Icon name="shield" size={16} />
              <span>Originals stay preserved.</span>
            </div>
          </aside>
        )}
      </div>
      {dialog && (
        <ExplorerActionModal
          kind={dialog}
          caseId={matter.id}
          selected={selected}
          spec={spec}
          close={() => setDialog(null)}
          done={() => {
            setDialog(null);
            saved.refresh();
            setVersion((value) => value + 1);
          }}
        />
      )}
    </div>
  );
}

function FilterSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="filter-section" open>
      <summary>
        {title}
        <Icon name="chevron" size={13} />
      </summary>
      <div>{children}</div>
    </details>
  );
}

export function EvidenceInspector({
  caseId,
  id,
  canReview,
  canPrivilege,
  close,
  changed,
  open,
}: {
  caseId: string;
  id: string;
  canReview: boolean;
  canPrivilege: boolean;
  close: () => void;
  changed: () => void;
  open: (id: string) => void;
}) {
  const detail = useResource<EvidenceDetail>(`/cases/${caseId}/evidence/${id}`);
  const custodians = useResource<{
    items: { id: string; display_name: string }[];
  }>(`/cases/${caseId}/custodians`);
  const [tab, setTab] = useState("content"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [message, setMessage] = useState(""),
    [verified, setVerified] = useState<{
      valid: boolean;
      expected_sha256: string;
      actual_sha256: string;
    } | null>(null),
    [raw, setRaw] = useState(false);
  const [tags, setTags] = useState(""),
    [note, setNote] = useState("");
  const data = detail.data;
  useEffect(() => {
    setTab("content");
    setError(null);
    setMessage("");
    setVerified(null);
    setRaw(false);
    setNote("");
  }, [id]);
  useEffect(() => {
    if (data) setTags(data.tags.join(", "));
  }, [data]);
  async function review(changes: Record<string, unknown>) {
    if (!data) return;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      await post(`/cases/${caseId}/evidence/${id}/reviews`, {
        ...changes,
        expected_version: data.review_version,
      });
      detail.refresh();
      changed();
      setMessage("Review saved in the audit record.");
    } catch (error) {
      setError(error);
      detail.refresh();
    } finally {
      setBusy(false);
    }
  }
  function people(value: unknown): string {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(people).join(", ");
    if (value && typeof value === "object") {
      const person = value as {
        name?: string;
        email?: string;
        address?: string;
      };
      return [person.name, person.email || person.address]
        .filter(Boolean)
        .join(" · ");
    }
    return "—";
  }
  return (
    <aside className="evidence-inspector" aria-label="Evidence inspector">
      <div className="inspector-top">
        <span className="eyebrow">EVIDENCE INSPECTOR</span>
        <button
          className="icon-button"
          aria-label="Close evidence inspector"
          onClick={close}
        >
          <Icon name="close" size={18} />
        </button>
      </div>
      <ErrorBox error={detail.error} retry={detail.refresh} />
      {detail.loading && !data ? (
        <Loading text="Opening evidence…" />
      ) : (
        data && (
          <>
            <div className="inspector-heading">
              <div className="inspector-badges">
                <Badge value={data.type} />
                <Badge value={data.parser_state} />
                {data.bookmarked && <Badge value="Bookmarked" tone="amber" />}
              </div>
              <h2>{data.title}</h2>
              <span className="mono">{data.evidence_id}</span>
              <div className="inspector-actions">
                <a
                  className="button secondary compact"
                  href={`/api/v1/cases/${caseId}/evidence/${id}/original`}
                >
                  <Icon name="export" size={15} />
                  Original
                </a>
                <button
                  className={`icon-button ${data.bookmarked ? "starred" : ""}`}
                  disabled={busy || !canReview}
                  aria-label={
                    data.bookmarked ? "Remove bookmark" : "Bookmark evidence"
                  }
                  onClick={() => void review({ bookmarked: !data.bookmarked })}
                >
                  <Icon name="star" size={18} />
                </button>
                <button
                  className="button ghost compact"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      setVerified(
                        await post(`/cases/${caseId}/evidence/${id}/verify`),
                      );
                    } catch (error) {
                      setError(error);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Icon name="shield" size={15} />
                  Verify
                </button>
              </div>
            </div>
            {verified && (
              <div
                className={`notice ${verified.valid ? "green" : "red"}`}
                role="status"
              >
                <Icon name={verified.valid ? "check" : "alert"} size={16} />
                <span>
                  {verified.valid
                    ? "Original hash verified."
                    : "Original hash mismatch. Source integrity requires investigation."}
                </span>
              </div>
            )}
            <div
              className="inspector-tabs"
              role="tablist"
              aria-label="Evidence details"
            >
              {[
                ["content", "Content"],
                ["metadata", "Source"],
                ["review", "Review"],
                ...(data.type === "email" ? [["thread", "Thread"]] : []),
              ].map(([key, title]) => (
                <button
                  key={key}
                  role="tab"
                  aria-selected={tab === key}
                  aria-controls={`inspector-${key}`}
                  id={`tab-${key}`}
                  onClick={() => setTab(key)}
                >
                  {title}
                </button>
              ))}
            </div>
            <div
              className="inspector-body"
              role="tabpanel"
              id={`inspector-${tab}`}
              aria-labelledby={`tab-${tab}`}
            >
              <ErrorBox error={error} />
              {message && (
                <div className="notice green" role="status">
                  <Icon name="check" size={16} />
                  {message}
                </div>
              )}
              {tab === "content" ? (
                <>
                  {data.email && (
                    <dl className="email-envelope">
                      <div>
                        <dt>From</dt>
                        <dd>{people(data.email.from)}</dd>
                      </div>
                      <div>
                        <dt>To</dt>
                        <dd>{people(data.email.to)}</dd>
                      </div>
                      {people(data.email.cc) !== "" &&
                        people(data.email.cc) !== "—" && (
                          <div>
                            <dt>CC</dt>
                            <dd>{people(data.email.cc)}</dd>
                          </div>
                        )}
                      <div>
                        <dt>Sent</dt>
                        <dd>{date(data.date_utc, true)}</dd>
                      </div>
                    </dl>
                  )}
                  <div className="text-viewer-heading">
                    <span>
                      {data.type === "pdf"
                        ? "EXTRACTED DOCUMENT TEXT"
                        : "EXTRACTED CONTENT"}
                    </span>
                    <Icon name="lock" size={13} />
                  </div>
                  {data.spans?.length ? (
                    <div className="text-viewer">
                      {data.spans.map((span, i) => (
                        <div
                          key={span.span_id || span.id || i}
                          className="text-span"
                          id={`span-${span.span_id || span.id}`}
                        >
                          <span className="span-anchor">
                            {span.page
                              ? `Page ${span.page}`
                              : `Chars ${span.char_start}–${span.char_end}`}{" "}
                            · v{span.artifact_version}
                          </span>
                          <p>{span.text}</p>
                          <button
                            className="citation-copy"
                            onClick={async () => {
                              try {
                                await navigator.clipboard.writeText(
                                  `${data.evidence_id} · ${span.page ? `page ${span.page}` : `chars ${span.char_start}-${span.char_end}`} · ${span.span_id || span.id}`,
                                );
                                setMessage("Source reference copied.");
                              } catch {
                                setMessage(
                                  "Select the evidence ID and location to copy the reference.",
                                );
                              }
                            }}
                          >
                            <Icon name="copy" size={12} />
                            Copy source reference
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : data.text ? (
                    <div className="text-viewer">
                      <p className="plain-text">{data.text}</p>
                    </div>
                  ) : (
                    <div className="notice amber">
                      <Icon name="alert" size={18} />
                      No extracted text is available. Review the original and
                      processing report.
                    </div>
                  )}
                  {data.attachments?.length > 0 && (
                    <div className="attachment-list">
                      <h3>
                        Attachment family{" "}
                        <span className="count-chip">
                          {data.attachments.length}
                        </span>
                      </h3>
                      {data.attachments.map((item) => (
                        <button
                          key={item.evidence_id}
                          onClick={() => open(item.evidence_id)}
                        >
                          <Icon name="file" size={18} />
                          <span>
                            <strong>{item.title}</strong>
                            <small>
                              {bytes(item.byte_size)} ·{" "}
                              {label(item.parser_state)}
                            </small>
                          </span>
                          <Icon name="chevron" size={15} />
                        </button>
                      ))}
                    </div>
                  )}
                  {(data.parent_id || data.parent_item_id) && (
                    <button
                      className="button secondary compact"
                      onClick={() =>
                        open((data.parent_id || data.parent_item_id)!)
                      }
                    >
                      <Icon name="back" size={15} />
                      Parent evidence
                    </button>
                  )}
                  {data.email && (
                    <div className="raw-header-section">
                      <button
                        className="text-link"
                        onClick={() => setRaw((value) => !value)}
                      >
                        {raw
                          ? "Hide original headers"
                          : "Show original headers"}
                        <Icon name="chevron" size={14} />
                      </button>
                      {raw && (
                        <pre>
                          {typeof data.email.raw_headers === "string"
                            ? data.email.raw_headers
                            : JSON.stringify(data.email.raw_headers, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </>
              ) : tab === "metadata" ? (
                <>
                  <h3>Source provenance</h3>
                  <dl className="metadata-list">
                    <Meta
                      title="Original filename"
                      value={data.original_name}
                    />
                    <Meta title="Source" value={data.source?.label} />
                    <Meta
                      title="Custodian"
                      value={
                        typeof data.source?.custodian === "string"
                          ? data.source.custodian
                          : data.source?.custodian?.display_name ||
                            custodians.data?.items.find(
                              (item) =>
                                item.id ===
                                (data.source?.custodian_id ||
                                  data.custodian_id),
                            )?.display_name
                      }
                    />
                    <Meta title="Evidence ID" value={data.evidence_id} />
                    <Meta
                      title="Preserved size"
                      value={bytes(data.byte_size)}
                    />
                    <Meta
                      title="Integrity state"
                      value={data.integrity_status}
                    />
                    <Meta title="Processing state" value={data.parser_state} />
                    <Meta title="UTC timestamp" value={data.date_utc} />
                    <Meta
                      title="Raw source time"
                      value={data.email?.sent_at_raw || data.date_raw}
                    />
                    <Meta
                      title="Time zone provenance"
                      value={data.timezone_source || "See original metadata"}
                    />
                  </dl>
                  <h3>Original SHA-256</h3>
                  <code className="hash-block">{data.sha256}</code>
                  <p className="field-help">
                    The hash identifies the exact original bytes, independently
                    of extracted text.
                  </p>
                  {data.derived_artifacts?.length ? (
                    <>
                      <h3>Derived artifacts</h3>
                      {data.derived_artifacts.map((artifact) => (
                        <div className="artifact-card" key={artifact.id}>
                          <strong>{label(artifact.artifact_type)}</strong>
                          <small>{artifact.parser_or_model_version}</small>
                          <code>{artifact.sha256}</code>
                        </div>
                      ))}
                    </>
                  ) : null}
                  {data.spans?.length ? (
                    <>
                      <h3>Source locations</h3>
                      <div className="span-list">
                        {data.spans.map((span, i) => (
                          <div key={span.span_id || span.id || i}>
                            <strong>
                              {span.page
                                ? `Page ${span.page}`
                                : `Characters ${span.char_start}–${span.char_end}`}
                            </strong>
                            <small className="mono">
                              {span.span_id || span.id}
                            </small>
                            <small>
                              Artifact version {span.artifact_version}
                            </small>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : null}
                </>
              ) : tab === "thread" ? (
                <ThreadView caseId={caseId} id={id} open={open} />
              ) : (
                <>
                  <div className="review-current">
                    <span className="eyebrow">HUMAN REVIEW</span>
                    <Badge value={data.review_status} />
                  </div>
                  <h3>Responsiveness</h3>
                  <div className="review-buttons">
                    {[
                      "responsive",
                      "non_responsive",
                      "needs_review",
                      "unreviewed",
                    ].map((status) => (
                      <button
                        key={status}
                        className={`button secondary compact ${data.review_status === status ? "chosen" : ""}`}
                        disabled={busy || !canReview}
                        onClick={() => void review({ review_status: status })}
                      >
                        {label(status)}
                      </button>
                    ))}
                  </div>
                  <h3>Privilege review</h3>
                  <p className="field-help">
                    Suspicion is a review flag. Confirmed privilege is a human
                    decision and can block export.
                  </p>
                  <select
                    aria-label="Privilege review status"
                    value={data.privilege_status || "none"}
                    disabled={
                      busy ||
                      !canReview ||
                      (data.privilege_status === "confirmed" && !canPrivilege)
                    }
                    onChange={(event) =>
                      void review({ privilege_status: event.target.value })
                    }
                  >
                    <option value="none">No privilege flag</option>
                    <option value="suspected">
                      Suspected · requires review
                    </option>
                    <option value="confirmed" disabled={!canPrivilege}>
                      Confirmed by attorney
                    </option>
                  </select>
                  <h3>Human tags</h3>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void review({
                        tags: tags
                          .split(",")
                          .map((tag) => tag.trim())
                          .filter(Boolean),
                      });
                    }}
                  >
                    <label>
                      <span className="sr-only">
                        Comma-separated evidence tags
                      </span>
                      <input
                        value={tags}
                        onChange={(event) => setTags(event.target.value)}
                        placeholder="Payment approval, Key witness"
                        disabled={!canReview}
                      />
                    </label>
                    <small className="field-help">
                      Separate tags with a comma.
                    </small>
                    <button
                      className="button secondary compact"
                      disabled={busy || !canReview}
                    >
                      Save tags
                    </button>
                  </form>
                  <h3>Review note</h3>
                  <form
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!note.trim()) return;
                      setBusy(true);
                      setError(null);
                      try {
                        await post(
                          `/cases/${caseId}/evidence/${id}/annotations`,
                          { text: note.trim() },
                        );
                        setNote("");
                        detail.refresh();
                        setMessage("Note saved.");
                      } catch (error) {
                        setError(error);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <label>
                      <span className="sr-only">Evidence review note</span>
                      <textarea
                        rows={3}
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="Add a note for your review team…"
                        required
                        disabled={!canReview}
                      />
                    </label>
                    <button
                      className="button secondary compact"
                      disabled={busy || !canReview || !note.trim()}
                    >
                      Add note
                    </button>
                  </form>
                  {data.annotations?.length > 0 && (
                    <div className="notes-list">
                      {data.annotations.map((note) => (
                        <div key={note.id}>
                          <p>{note.text}</p>
                          <small>{date(note.created_at, true)}</small>
                        </div>
                      ))}
                    </div>
                  )}
                  {data.review_history?.length > 0 && (
                    <>
                      <h3>Review history</h3>
                      <div className="notes-list">
                        {data.review_history.map((item) => (
                          <div key={item.id}>
                            <strong>
                              {item.review_status || item.changes?.review_status
                                ? label(
                                    (item.review_status ||
                                      item.changes?.review_status)!,
                                  )
                                : "Review updated"}
                            </strong>
                            {item.note && <p>{item.note}</p>}
                            <small>
                              {date(item.decided_at || item.created_at, true)}
                            </small>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                  {!canReview && (
                    <div className="notice subtle">
                      <Icon name="lock" size={16} />
                      Your matter role allows reading this evidence. Review
                      changes require additional permission.
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        )
      )}
    </aside>
  );
}

function Meta({
  title,
  value,
}: {
  title: string;
  value?: string | number | null;
}) {
  return (
    <div>
      <dt>{title}</dt>
      <dd>{value || "Not recorded"}</dd>
    </div>
  );
}

function ExplorerActionModal({
  kind,
  caseId,
  selected,
  spec,
  close,
  done,
}: {
  kind: "saved" | "set" | "bulk" | "export";
  caseId: string;
  selected: string[];
  spec: SearchSpec;
  close: () => void;
  done: () => void;
}) {
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [download, setDownload] = useState<{ id: string; state: string } | null>(
      null,
    );
  const exportStatus = useResource<{ id: string; state: string }>(
    download &&
      !["completed", "ready", "failed"].includes(download.state.toLowerCase())
      ? `/cases/${caseId}/exports/${download.id}`
      : null,
  );
  useEffect(() => {
    if (exportStatus.data) setDownload(exportStatus.data);
  }, [exportStatus.data]);
  useEffect(() => {
    if (
      !download ||
      ["completed", "ready", "failed"].includes(download.state.toLowerCase())
    )
      return;
    const timer = setInterval(exportStatus.refresh, 1500);
    return () => clearInterval(timer);
  }, [download, exportStatus.refresh]);
  const titles = {
    saved: "Save this search",
    set: "Create a review set",
    bulk: "Review selected evidence",
    export: "Export this evidence scope",
  };
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      if (kind === "saved")
        await post(`/cases/${caseId}/saved-searches`, {
          name: form.get("name"),
          query_spec: { ...spec, cursor: null },
        });
      if (kind === "set")
        await post(`/cases/${caseId}/review-sets`, {
          name: form.get("name"),
          evidence_ids: selected,
        });
      if (kind === "bulk")
        await post(`/cases/${caseId}/reviews/bulk`, {
          evidence_ids: selected,
          changes: {
            review_status: form.get("review_status"),
            ...(form.get("tags")
              ? {
                  tags: String(form.get("tags"))
                    .split(",")
                    .map((tag) => tag.trim())
                    .filter(Boolean),
                }
              : {}),
          },
        });
      if (kind === "export") {
        setDownload(
          await post(`/cases/${caseId}/exports`, {
            format: form.get("format"),
            ...(selected.length
              ? { evidence_ids: selected }
              : { query_spec: { ...spec, cursor: null } }),
            reason: form.get("reason"),
            confirmed: form.get("confirmed") === "on",
          }),
        );
      } else done();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={titles[kind]} close={close}>
      <ErrorBox error={error} />
      {download ? (
        <>
          <div className="notice green" role="status">
            <Icon name="check" />
            Export {label(download.state).toLowerCase()}.
          </div>
          <p className="muted">
            The server checked your permissions, evidence integrity and export
            holdbacks.
          </p>
          {["completed", "ready"].includes(download.state.toLowerCase()) ? (
            <a
              className="button primary"
              href={`/api/v1/cases/${caseId}/exports/${download.id}/download`}
            >
              <Icon name="export" size={17} />
              Download export
            </a>
          ) : (
            <Link
              href={`/app/matters/${caseId}/reports`}
              className="button primary"
            >
              View export status
              <Icon name="arrow" size={16} />
            </Link>
          )}
        </>
      ) : (
        <form onSubmit={submit}>
          <p className="muted">
            {kind === "saved"
              ? "Preserve this query, filters, sort and grouping so you can return to the same scope."
              : selected.length
                ? `${number(selected.length)} explicitly selected evidence items.`
                : "All evidence matching the current query and filters, across every page."}
          </p>
          {["saved", "set"].includes(kind) && (
            <label>
              Name
              <input
                name="name"
                required
                maxLength={200}
                placeholder={
                  kind === "saved"
                    ? "Finance correspondence · Q2"
                    : "First-pass review"
                }
              />
            </label>
          )}
          {kind === "bulk" && (
            <>
              <label>
                Review decision
                <select name="review_status">
                  <option value="needs_review">Needs review</option>
                  <option value="responsive">Responsive</option>
                  <option value="non_responsive">Non-responsive</option>
                  <option value="unreviewed">Unreviewed</option>
                </select>
              </label>
              <label>
                Tags <span className="optional">optional</span>
                <input name="tags" placeholder="Comma-separated tags" />
              </label>
            </>
          )}
          {kind === "export" && (
            <>
              <label>
                Format
                <select name="format">
                  <option value="csv">CSV metadata + hash manifest</option>
                  <option value="json">JSON metadata + hash manifest</option>
                  <option value="zip">ZIP evidence package + manifest</option>
                </select>
              </label>
              <label>
                Purpose or reason
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  rows={3}
                  placeholder="Describe the purpose of this export"
                />
              </label>
              <label className="checkbox-label">
                <input name="confirmed" type="checkbox" required />
                <span>
                  I reviewed the evidence scope and am authorized to export it.
                </span>
              </label>
              <div className="notice amber">
                <Icon name="lock" size={17} />
                <span>
                  Server privilege, confidentiality and integrity checks can
                  block this export. Preview exports are limited to 20,000
                  items.
                </span>
              </div>
            </>
          )}
          <div className="form-actions">
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={close}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              {busy
                ? "Saving…"
                : kind === "export"
                  ? "Create export"
                  : kind === "bulk"
                    ? "Save review decisions"
                    : "Save"}
              <Icon name="arrow" size={16} />
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
