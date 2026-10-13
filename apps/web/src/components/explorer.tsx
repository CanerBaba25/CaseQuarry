"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  bytes,
  date,
  getDisplayTimeZone,
  label,
  number,
  post,
} from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import { bucketRange, filtersFromParams } from "@/lib/search-scope";
import type {
  Evidence,
  EvidenceDetail,
  Matter,
  Member,
  SavedSearch,
  SearchResult,
  SearchSpec,
  Source,
  Span,
} from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { Pagination } from "./matter-pages";
import ThreadView from "./thread-view";
import SourceInvestigations from "./source-investigations";

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
  const router = useRouter(),
    params = useSearchParams(),
    routeQuery = params.toString();
  const [spec, setSpec] = useState<SearchSpec>(() => ({
    ...defaultSpec,
    filters: {
      ...(reviewOnly ? { review_status: ["unreviewed", "needs_review"] } : {}),
      ...(emailOnly ? { item_types: ["email"] } : {}),
    },
  }));
  const [draft, setDraft] = useState(""),
    [loadedResult, setLoadedResult] = useState<{
      key: string;
      value: SearchResult;
    } | null>(null),
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
    "saved" | "set" | "bulk" | "export" | "assign" | null
  >(null);
  const sources = useResource<{ items: Source[] }>(
      `/cases/${matter.id}/sources`,
    ),
    saved = useResource<{ items: SavedSearch[] }>(
      `/cases/${matter.id}/saved-searches`,
    );
  const custodians = useResource<{
    items: { id: string; display_name: string }[];
  }>(`/cases/${matter.id}/custodians`);
  const members = useResource<{ items: Member[] }>(
    `/cases/${matter.id}/members`,
  );
  const requestKey = JSON.stringify([matter.id, spec]);
  const result = loadedResult?.key === requestKey ? loadedResult.value : null;
  const person = useResource<{ email: string; name: string }>(
    spec.filters.person_id
      ? `/cases/${matter.id}/people/${spec.filters.person_id}`
      : null,
  );
  const canReview = can(matter.role, "review");
  const canPrivilege = can(matter.role, "privilege");
  const canExport = can(matter.role, "export");
  useEffect(() => {
    const params = new URLSearchParams(routeQuery);
    const query = params.get("q") || "";
    setDraft(query);
    setHistory([]);
    setSelected([]);
    setSelectedId(evidenceId || null);
    setSpec({
      ...defaultSpec,
      query,
      filters: {
        ...(reviewOnly
          ? { review_status: ["unreviewed", "needs_review"] }
          : {}),
        ...filtersFromParams(params),
        ...(emailOnly ? { item_types: ["email"] } : {}),
      },
    });
  }, [matter.id, reviewOnly, emailOnly, evidenceId, routeQuery]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    post<SearchResult>(`/cases/${matter.id}/search`, spec, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted)
          setLoadedResult({ key: requestKey, value });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [matter.id, spec, version, requestKey]);
  function update(changes: Partial<SearchSpec>) {
    setSpec((current) => ({
      ...current,
      ...changes,
      ...(changes.filters && emailOnly
        ? { filters: { ...changes.filters, item_types: ["email"] } }
        : {}),
      cursor: null,
    }));
    setHistory([]);
    setSelected([]);
  }
  function filter(key: string, value: unknown) {
    const filters = { ...spec.filters };
    if (
      value === null ||
      value === "" ||
      (Array.isArray(value) && value.length === 0)
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
  const activeFilters = Object.entries(spec.filters)
    .filter(([key]) => !emailOnly || key !== "item_types")
    .flatMap(([key, value]) =>
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
      custodian: "custodian_ids",
      privilege_status: "privilege_status",
      reviewer: "assigned_to",
      tag: "tags",
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
          <h1>
            {reviewOnly
              ? "Review queue"
              : emailOnly
                ? "Email explorer"
                : "Evidence explorer"}
          </h1>
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
              <option value="size:asc">Smallest first</option>
              <option value="sender:asc">Sender A–Z</option>
              <option value="imported_at:desc">Recently imported</option>
              <option value="imported_at:asc">First imported</option>
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
              <option value="day">Day</option>
              <option value="year">Year</option>
              <option value="type">File type</option>
              <option value="source">Source</option>
              <option value="review_status">Review status</option>
              <option value="thread">Thread</option>
              <option value="custodian">Custodian</option>
              <option value="privilege_status">Privilege status</option>
              <option value="reviewer">Assigned reviewer</option>
              <option value="tag">Tag</option>
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
                  ? item.value
                    ? "Yes"
                    : "No"
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
            {(emailOnly ? ["email"] : types).map((type) => {
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
                    disabled={emailOnly}
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
              Custodian
              <select
                value={
                  ((spec.filters.custodian_ids || []) as string[])[0] || ""
                }
                onChange={(event) =>
                  filter(
                    "custodian_ids",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">All custodians</option>
                {custodians.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
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
            <label className="filter-field">
              Recipient
              <input
                value={String(spec.filters.recipient || "")}
                onChange={(event) => filter("recipient", event.target.value)}
                placeholder="Address contains…"
              />
            </label>
            <label className="filter-field">
              Attachments
              <select
                value={
                  typeof spec.filters.has_attachment === "boolean"
                    ? String(spec.filters.has_attachment)
                    : ""
                }
                onChange={(event) =>
                  filter(
                    "has_attachment",
                    event.target.value === ""
                      ? null
                      : event.target.value === "true",
                  )
                }
              >
                <option value="">With or without</option>
                <option value="true">With attachments</option>
                <option value="false">Without attachments</option>
              </select>
            </label>
            <ErrorBox error={sources.error || custodians.error} />
          </FilterSection>
          <FilterSection title="Date · UTC">
            <label className="filter-field">
              Date field
              <select
                value={String(spec.filters.date_field || "sent_at")}
                onChange={(event) => filter("date_field", event.target.value)}
              >
                <option value="sent_at">Source timestamp</option>
                <option value="imported_at">Imported timestamp</option>
              </select>
            </label>
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
            <label className="filter-field">
              Timestamp availability
              <select
                value={
                  typeof spec.filters.missing_date === "boolean"
                    ? String(spec.filters.missing_date)
                    : ""
                }
                onChange={(event) =>
                  filter(
                    "missing_date",
                    event.target.value === ""
                      ? null
                      : event.target.value === "true",
                  )
                }
              >
                <option value="">Dated and undated</option>
                <option value="true">Missing timestamp</option>
                <option value="false">Has timestamp</option>
              </select>
            </label>
          </FilterSection>
          <FilterSection title="Review & processing">
            <label className="filter-field">
              Privilege status
              <select
                value={
                  ((spec.filters.privilege_status || []) as string[])[0] || ""
                }
                onChange={(event) =>
                  filter(
                    "privilege_status",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">All determinations</option>
                {["none", "suspected", "confirmed", "cleared"].map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              Processing state
              <select
                value={((spec.filters.parser_state || []) as string[])[0] || ""}
                onChange={(event) =>
                  filter(
                    "parser_state",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">All processing states</option>
                {[
                  "indexed",
                  "stored",
                  "pending",
                  "partial",
                  "failed",
                  "unsupported",
                  "locked",
                  "quarantined",
                ].map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              Assigned reviewer
              <select
                value={String(spec.filters.assigned_to || "")}
                onChange={(event) => filter("assigned_to", event.target.value)}
              >
                <option value="">All reviewers</option>
                {members.data?.items.map((item) => (
                  <option key={item.user_id} value={item.user_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              Tag
              <input
                value={((spec.filters.tags || []) as string[]).join(", ")}
                onChange={(event) =>
                  filter(
                    "tags",
                    event.target.value
                      .split(",")
                      .map((value) => value.trim())
                      .filter(Boolean),
                  )
                }
                placeholder="Exact tags, comma separated"
              />
            </label>
            <label className="facet-option">
              <input
                type="checkbox"
                checked={spec.filters.bookmarked === true}
                onChange={(event) =>
                  filter("bookmarked", event.target.checked ? true : null)
                }
              />
              <span>Bookmarked only</span>
            </label>
            <ErrorBox error={members.error} />
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
                <small>Full-scope counts · up to 200 returned groups</small>
              </div>
              <div className="group-chips">
                {result.groups.map((item) => (
                  <button
                    key={item.key}
                    disabled={
                      !item.key ||
                      item.key === "Unknown" ||
                      item.key === "Untagged"
                    }
                    title={
                      !item.key || item.key === "Unknown"
                        ? "Missing metadata cannot be drilled down in this preview. These items remain in the evidence results."
                        : undefined
                    }
                    onClick={() => {
                      if (
                        ["month", "year", "day"].includes(spec.group_by || "")
                      ) {
                        update({
                          filters: {
                            ...spec.filters,
                            ...bucketRange(item.key, spec.group_by!),
                            date_field: "sent_at",
                          },
                        });
                      } else
                        filter(
                          groupField,
                          ["sender", "thread_id", "assigned_to"].includes(
                            groupField,
                          )
                            ? item.key
                            : [item.key],
                        );
                    }}
                  >
                    <span>
                      {spec.group_by === "source"
                        ? sources.data?.items.find(
                            (source) => source.id === item.key,
                          )?.label || item.key
                        : spec.group_by === "custodian"
                          ? custodians.data?.items.find(
                              (custodian) => custodian.id === item.key,
                            )?.display_name || item.key
                          : spec.group_by === "reviewer"
                            ? members.data?.items.find(
                                (member) => member.user_id === item.key,
                              )?.name || item.key
                            : item.key || "Not recorded"}
                    </span>
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
                {can(matter.role, "manage") && (
                  <button
                    className="button secondary compact"
                    onClick={() => setDialog("assign")}
                  >
                    Assign selected
                  </button>
                )}
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
            {loading || (!result && !error) ? (
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
                    <th>Date · {getDisplayTimeZone()}</th>
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
                              {emailOnly && item.recipients.length > 0 && (
                                <span> → {item.recipients.join(", ")}</span>
                              )}
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
            key={`${matter.id}:${selectedId}`}
            caseId={matter.id}
            id={selectedId}
            canReview={canReview}
            canPrivilege={canPrivilege}
            canManage={can(matter.role, "manage")}
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
  canReview: allowReview,
  canPrivilege,
  canManage: allowManage = false,
  close,
  changed,
  open,
}: {
  caseId: string;
  id: string;
  canReview: boolean;
  canPrivilege: boolean;
  canManage?: boolean;
  close: () => void;
  changed: () => void;
  open: (id: string) => void;
}) {
  const path = usePathname(),
    params = useSearchParams(),
    versionRouter = useRouter(),
    version = path.endsWith(`/evidence/${id}`) ? params.get("version") : null;
  const canReview = allowReview && !version,
    canManage = allowManage && !version;
  const reviewScope = `${caseId}:${id}:${version || "current"}`;
  const activeReviewScope = useRef<string | null>(reviewScope);
  activeReviewScope.current = reviewScope;
  useEffect(() => {
    activeReviewScope.current = reviewScope;
    return () => {
      activeReviewScope.current = null;
    };
  }, [reviewScope]);
  const detail = useResource<EvidenceDetail>(`/cases/${caseId}/evidence/${id}`);
  const historical = useResource<{
    text: string;
    spans: Span[];
    artifact_version: number;
    current_version: number;
    superseded: boolean;
    warnings?: string[];
  }>(
    version
      ? `/cases/${caseId}/evidence/${id}/content?version=${encodeURIComponent(version)}`
      : null,
  );
  const versions = useResource<{
    items: {
      version: number;
      current: boolean;
      sha256: string;
      created_at: string;
    }[];
    current_version: number;
    before_version: number | null;
  }>(`/cases/${caseId}/evidence/${id}/versions`);
  const custodians = useResource<{
    items: { id: string; display_name: string }[];
  }>(`/cases/${caseId}/custodians`);
  const members = useResource<{ items: Member[] }>(`/cases/${caseId}/members`);
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
    [note, setNote] = useState(""),
    [noteSpan, setNoteSpan] = useState<string | null>(null);
  const tagDraft = useRef({ dirty: false, revision: 0 });
  const data = useMemo(
    () =>
      !detail.data
        ? null
        : version
          ? historical.data
            ? {
                ...detail.data,
                text: historical.data.text,
                spans: historical.data.spans,
                artifact_version: historical.data.artifact_version,
              }
            : null
          : detail.data,
    [detail.data, historical.data, version],
  );
  useEffect(() => {
    setTab("content");
    setError(null);
    setMessage("");
    setVerified(null);
    setRaw(false);
    setNote("");
    setNoteSpan(null);
    setBusy(false);
    tagDraft.current = {
      dirty: false,
      revision: tagDraft.current.revision + 1,
    };
    setTags("");
  }, [caseId, id, version]);
  useEffect(() => {
    if (data && !tagDraft.current.dirty) setTags(data.tags.join(", "));
  }, [data]);
  useEffect(() => {
    if (!data || !window.location.hash.startsWith("#span-")) return;
    document
      .getElementById(window.location.hash.slice(1))
      ?.scrollIntoView({ block: "center" });
  }, [data]);
  async function review(changes: Record<string, unknown>) {
    if (!data) return;
    const submittedDraftRevision = tagDraft.current.revision;
    const submittedScope = reviewScope;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const reviewed = await post<Evidence>(
        `/cases/${caseId}/evidence/${id}/reviews`,
        {
          ...changes,
          expected_version: data.review_version,
        },
      );
      if (activeReviewScope.current !== submittedScope) return;
      detail.setData((current) =>
        current &&
        current.id === reviewed.id &&
        current.review_version <= reviewed.review_version
          ? { ...current, ...reviewed }
          : current,
      );
      if (
        "tags" in changes &&
        tagDraft.current.revision === submittedDraftRevision
      ) {
        tagDraft.current.dirty = false;
        setTags(reviewed.tags.join(", "));
      }
      detail.refresh();
      changed();
      setMessage("Review saved in the audit record.");
    } catch (error) {
      if (activeReviewScope.current === submittedScope) {
        setError(error);
        detail.refresh();
      }
    } finally {
      if (activeReviewScope.current === submittedScope) setBusy(false);
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
      <ErrorBox
        error={detail.error || historical.error}
        retry={() => {
          detail.refresh();
          historical.refresh();
        }}
      />
      {(detail.loading || historical.loading) && !data ? (
        <Loading text="Opening evidence…" />
      ) : (
        data && (
          <>
            {version && (
              <div className="notice amber" role="status">
                <Icon name="lock" size={17} />
                <span>
                  {historical.data?.superseded
                    ? `Superseded extraction v${version}; the current version is v${historical.data.current_version}.`
                    : `Version-specific extraction v${version}.`}{" "}
                  This view is read-only. Current review and production use the
                  latest extraction.{" "}
                  <Link
                    className="text-link"
                    href={`/app/matters/${caseId}/evidence/${id}`}
                  >
                    Open current evidence
                  </Link>
                </span>
              </div>
            )}
            <label className="inspector-version-select">
              Extracted text version
              <select
                value={version || "current"}
                aria-label="Extracted text version"
                onChange={(event) =>
                  versionRouter.push(
                    `/app/matters/${caseId}/evidence/${id}${event.target.value === "current" ? "" : `?version=${event.target.value}`}`,
                  )
                }
              >
                <option value="current">
                  Current extraction
                  {versions.data?.current_version
                    ? ` · v${versions.data.current_version}`
                    : ""}
                </option>
                {version &&
                  !versions.data?.items.some(
                    (item) => String(item.version) === version,
                  ) && (
                    <option value={version}>Cited extraction v{version}</option>
                  )}
                {versions.data?.items.map((item) => (
                  <option key={item.version} value={String(item.version)}>
                    v{item.version} · {item.current ? "current" : "superseded"}
                  </option>
                ))}
              </select>
              {versions.data?.before_version && (
                <small>
                  Showing the latest 50 versions. Older versions remain
                  addressable by their exact version link.
                </small>
              )}
            </label>
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
                {canReview && (
                  <Link
                    className="button secondary compact"
                    href={`/app/matters/${caseId}/productions?evidence_id=${id}`}
                  >
                    Redact
                  </Link>
                )}
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
            {data.integrity_status === "failed" && (
              <div className="notice red" role="alert">
                <Icon name="alert" size={17} />
                <span>
                  Original integrity verification failed. Download is blocked;
                  investigate the preserved source.
                </span>
              </div>
            )}
            {data.parser_error && (
              <div className="notice amber">
                <Icon name="alert" size={17} />
                <span>
                  Extraction limitation: {label(data.parser_error)}. Review the
                  original and import report for full coverage.
                </span>
              </div>
            )}
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
                ...(!version ? [["investigate", "Investigate"]] : []),
                ...(data.type === "email" ? [["thread", "Thread"]] : []),
              ].map(([key, title]) => (
                <button
                  key={key}
                  role="tab"
                  aria-selected={tab === key}
                  tabIndex={tab === key ? 0 : -1}
                  aria-controls={`inspector-${key}`}
                  id={`tab-${key}`}
                  onClick={() => setTab(key)}
                  onKeyDown={(event) => {
                    if (
                      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                        event.key,
                      )
                    )
                      return;
                    event.preventDefault();
                    const keys = [
                      "content",
                      "metadata",
                      "review",
                      ...(data.type === "email" ? ["thread"] : []),
                    ];
                    const position = keys.indexOf(key);
                    const target =
                      event.key === "Home"
                        ? keys[0]
                        : event.key === "End"
                          ? keys[keys.length - 1]
                          : keys[
                              (position +
                                (event.key === "ArrowRight" ? 1 : -1) +
                                keys.length) %
                                keys.length
                            ];
                    setTab(target);
                    document.getElementById(`tab-${target}`)?.focus();
                  }}
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
                      {!["", "—"].includes(people(data.email.bcc)) && (
                        <div>
                          <dt>BCC</dt>
                          <dd>{people(data.email.bcc)}</dd>
                        </div>
                      )}
                      {!["", "—"].includes(people(data.email.reply_to)) && (
                        <div>
                          <dt>Reply-To</dt>
                          <dd>{people(data.email.reply_to)}</dd>
                        </div>
                      )}
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
                          {canReview && (
                            <button
                              className="citation-copy"
                              onClick={() => {
                                setNoteSpan(span.span_id || span.id);
                                setTab("review");
                              }}
                            >
                              <Icon name="review" size={12} />
                              Note this location
                            </button>
                          )}
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
                  {data.metadata && Object.keys(data.metadata).length > 0 && (
                    <>
                      <h3>Extraction metadata</h3>
                      {Boolean(data.metadata.ocr_quality) && (
                        <div className="notice amber">
                          <Icon name="alert" size={16} />
                          <span>
                            OCR text and confidence scores require human
                            verification against the source. They do not
                            establish evidentiary accuracy.
                          </span>
                        </div>
                      )}
                      <dl className="metadata-list">
                        {[
                          "extraction_method",
                          "ocr_engine",
                          "ocr_language",
                          "ocr_quality",
                          "format",
                          "encoding",
                        ]
                          .filter((key) => data.metadata?.[key])
                          .map((key) => (
                            <Meta
                              key={key}
                              title={label(key)}
                              value={String(data.metadata![key])}
                            />
                          ))}
                      </dl>
                      <details className="audit-metadata">
                        <summary>All parser metadata</summary>
                        <pre>{JSON.stringify(data.metadata, null, 2)}</pre>
                      </details>
                    </>
                  )}
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
              ) : tab === "investigate" ? (
                <SourceInvestigations
                  key={id}
                  caseId={caseId}
                  id={id}
                  open={open}
                />
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
                      (["confirmed", "cleared"].includes(
                        data.privilege_status,
                      ) &&
                        !canPrivilege)
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
                    <option value="cleared" disabled={!canPrivilege}>
                      Cleared by attorney
                    </option>
                  </select>
                  <h3>Assigned reviewer</h3>
                  <label>
                    <span className="sr-only">Evidence assigned reviewer</span>
                    <select
                      value={data.assigned_to || ""}
                      disabled={!canManage || busy}
                      onChange={(event) =>
                        void review({ assigned_to: event.target.value || null })
                      }
                    >
                      <option value="">Unassigned</option>
                      {members.data?.items
                        .filter((member) => can(member.role, "review"))
                        .map((member) => (
                          <option key={member.user_id} value={member.user_id}>
                            {member.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <p className="field-help">
                    Matter leads and review managers can change direct
                    allocation. Reviewers claim fixed snapshots from the review
                    queue.
                  </p>
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
                        onChange={(event) => {
                          tagDraft.current = {
                            dirty: true,
                            revision: tagDraft.current.revision + 1,
                          };
                          setTags(event.target.value);
                        }}
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
                  <label>
                    Source location
                    <select
                      value={noteSpan || ""}
                      onChange={(event) =>
                        setNoteSpan(event.target.value || null)
                      }
                      disabled={!canReview}
                    >
                      <option value="">General evidence note</option>
                      {data.spans.map((span) => (
                        <option key={span.id} value={span.span_id || span.id}>
                          {span.page
                            ? `Page ${span.page}`
                            : `Chars ${span.char_start}–${span.char_end}`}{" "}
                          · {span.span_id || span.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <form
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!note.trim()) return;
                      setBusy(true);
                      setError(null);
                      try {
                        await post(
                          `/cases/${caseId}/evidence/${id}/annotations`,
                          {
                            text: note.trim(),
                            ...(noteSpan ? { span_id: noteSpan } : {}),
                          },
                        );
                        setNote("");
                        setNoteSpan(null);
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
                          {note.span_id && (
                            <button
                              className="text-link"
                              onClick={() => {
                                setTab("content");
                                setTimeout(
                                  () =>
                                    document
                                      .getElementById(`span-${note.span_id}`)
                                      ?.scrollIntoView({ block: "center" }),
                                  0,
                                );
                              }}
                            >
                              Open anchored location
                            </button>
                          )}
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
  kind: "saved" | "set" | "bulk" | "export" | "assign";
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
  const members = useResource<{ items: Member[] }>(
    kind === "assign" ? `/cases/${caseId}/members` : null,
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
    assign: "Assign selected evidence",
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
      if (kind === "assign")
        await post(`/cases/${caseId}/assignments`, {
          title: form.get("name"),
          evidence_ids: selected,
          assignee_id: form.get("assignee_id") || null,
          reason: form.get("reason"),
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
          {["saved", "set", "assign"].includes(kind) && (
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
          {kind === "assign" && (
            <>
              <ErrorBox error={members.error} />
              <label>
                Assigned reviewer
                <select name="assignee_id" defaultValue="">
                  <option value="">Unassigned · available to claim</option>
                  {members.data?.items
                    .filter((member) => can(member.role, "review"))
                    .map((member) => (
                      <option key={member.user_id} value={member.user_id}>
                        {member.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Assignment reason
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={3}
                />
              </label>
              <p className="field-help">
                The selected items form a fixed snapshot. Items already reserved
                by another open assignment are rejected.
              </p>
            </>
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
                  Server privilege, review and integrity checks can block this
                  export. Preview exports are limited to 20,000 items.
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
