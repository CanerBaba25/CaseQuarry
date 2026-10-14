"use client";
import {
  getInterfaceLanguage,
  uiMessage,
  uiText,
  type InterfaceMessage,
  type MessageKey,
} from "@/lib/i18n";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  bytes,
  date,
  getDisplayTimeZone,
  uiLabel as label,
  number,
  post,
} from "@/lib/api";
import { useMountedRef, useResource } from "@/lib/hooks";
import type { RefreshScope } from "@/lib/sync";
import { can } from "@/lib/permissions";
import { dateBucketFilters, filtersFromParams } from "@/lib/search-scope";
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
import navigationStyles from "./explorer-navigation.module.css";

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

function searchFromRoute(
  query: string,
  reviewOnly: boolean,
  emailOnly: boolean,
): SearchSpec {
  const params = new URLSearchParams(query);
  return {
    ...defaultSpec,
    query: params.get("q") || "",
    filters: {
      ...(reviewOnly ? { review_status: ["unreviewed", "needs_review"] } : {}),
      ...filtersFromParams(params),
      ...(emailOnly ? { item_types: ["email"] } : {}),
    },
  };
}

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
  const [spec, setSpec] = useState<SearchSpec>(() =>
    searchFromRoute(routeQuery, reviewOnly, emailOnly),
  );
  const routeScope = JSON.stringify([
    matter.id,
    reviewOnly,
    emailOnly,
    evidenceId,
    routeQuery,
  ]);
  const appliedRoute = useRef(routeScope);
  const routeChanged = appliedRoute.current !== routeScope;
  const activeSearch = useRef<AbortController | null>(null);
  const [draft, setDraft] = useState(() => params.get("q") || ""),
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
  const [inspectorBlocked, setInspectorBlocked] = useState(false);
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
  const result =
    !routeChanged && loadedResult?.key === requestKey
      ? loadedResult.value
      : null;
  const selectedPosition =
    result?.items.findIndex((item) => item.evidence_id === selectedId) ?? -1;
  const person = useResource<{ email: string; name: string }>(
    spec.filters.person_id
      ? `/cases/${matter.id}/people/${spec.filters.person_id}`
      : null,
  );
  const canReview = can(matter.role, "review");
  const canPrivilege = can(matter.role, "privilege");
  const canExport = can(matter.role, "export");
  useEffect(() => {
    if (appliedRoute.current === routeScope) return;
    appliedRoute.current = routeScope;
    const next = searchFromRoute(routeQuery, reviewOnly, emailOnly);
    setDraft(next.query);
    setHistory([]);
    setSelected([]);
    setSelectedId(evidenceId || null);
    setDialog(null);
    setSpec(next);
  }, [matter.id, reviewOnly, emailOnly, evidenceId, routeQuery, routeScope]);
  useEffect(() => {
    function receive(event: Event) {
      const scope = (event as CustomEvent<RefreshScope>).detail || {
        system: true,
      };
      if (!scope.system && scope.caseId !== matter.id) return;
      activeSearch.current?.abort();
      if (scope.clear) {
        setLoadedResult(null);
        setSelected([]);
        setSelectedId(null);
      }
      setVersion((value) => value + 1);
    }
    window.addEventListener("cq:refresh", receive);
    return () => window.removeEventListener("cq:refresh", receive);
  }, [matter.id]);
  useEffect(() => {
    if (routeChanged) return;
    const controller = new AbortController();
    activeSearch.current = controller;
    setLoading(true);
    setError(null);
    post<SearchResult>(`/cases/${matter.id}/search`, spec, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted)
          setLoadedResult({ key: requestKey, value });
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          if (
            error instanceof ApiError &&
            [401, 403, 404].includes(error.status)
          ) {
            setLoadedResult(null);
            setSelected([]);
            setSelectedId(null);
          }
          setError(error);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (activeSearch.current === controller) activeSearch.current = null;
    };
  }, [matter.id, spec, version, requestKey, routeChanged]);
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
  const dateGrouping = ["month", "year", "day"].includes(spec.group_by || "");
  const importDateScope = Boolean(
    dateGrouping &&
    spec.filters.date_field === "imported_at" &&
    (spec.filters.date_from || spec.filters.date_to),
  );
  return (
    <div className="explorer-shell">
      <div className="explorer-heading">
        <div>
          <span className="eyebrow">
            {matter.matter_number} ·{" "}
            {reviewOnly
              ? uiText("HUMAN REVIEW")
              : uiText("THE EVIDENCE RECORD")}
          </span>
          <h1>
            {reviewOnly
              ? uiText("Review queue")
              : emailOnly
                ? uiText("Email explorer")
                : uiText("Evidence explorer")}
          </h1>
        </div>
        <div className="explorer-heading-actions">
          <button
            className="button secondary compact"
            onClick={() => setDialog("saved")}
          >
            <Icon name="star" size={16} />
            {uiText("Save search")}
          </button>
          <Link
            href={`/app/matters/${matter.id}/sources`}
            className="button primary compact"
          >
            <Icon name="upload" size={16} />
            {uiText("Import")}
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
          placeholder={uiText(
            'Search evidence… e.g. "payment approved" AND invoice',
          )}
          aria-label={uiText("Search evidence")}
        />
        <button
          type="submit"
          className="button primary compact"
          disabled={loading}
        >
          {uiText("Search")}
          <Icon name="arrow" size={16} />
        </button>
      </form>
      <div className="explorer-toolbar">
        <button
          className={`button secondary compact filter-toggle ${activeFilters.length ? "selected" : ""}`}
          onClick={() => setFiltersOpen((value) => !value)}
        >
          <Icon name="filter" size={15} />
          {uiText("Filters")}
          {activeFilters.length ? ` (${activeFilters.length})` : ""}
        </button>
        <div className="results-label" role="status">
          {loading
            ? uiText("Searching…")
            : getInterfaceLanguage() === "en"
              ? `${number(result?.total_hits)} ${result?.total_hits === 1 ? "result" : "results"}`
              : `${uiText("Search results")}: ${number(result?.total_hits)}`}
          <span>{uiText("Keyword search · This matter")}</span>
        </div>
        <div className="toolbar-selects">
          <label>
            {uiText("Sort")}
            <select
              aria-label={uiText("Sort evidence")}
              value={`${spec.sort[0].field}:${spec.sort[0].order}`}
              onChange={(event) => {
                const [field, order] = event.target.value.split(":");
                update({ sort: [{ field, order }] });
              }}
            >
              <option value="sent_at:desc">{uiText("Newest first")}</option>
              <option value="sent_at:asc">{uiText("Oldest first")}</option>
              <option value="title:asc">{uiText("Title A–Z")}</option>
              <option value="size:desc">{uiText("Largest first")}</option>
              <option value="size:asc">{uiText("Smallest first")}</option>
              <option value="sender:asc">{uiText("Sender A–Z")}</option>
              <option value="imported_at:desc">
                {uiText("Recently imported")}
              </option>
              <option value="imported_at:asc">
                {uiText("First imported")}
              </option>
              <option value="evidence_id:asc">{uiText("Evidence ID")}</option>
            </select>
          </label>
          <label>
            {uiText("Group")}
            <select
              aria-label={uiText("Group evidence")}
              value={spec.group_by || ""}
              onChange={(event) =>
                update({ group_by: event.target.value || null })
              }
            >
              <option value="">{uiText("No grouping")}</option>
              <option value="sender">{uiText("Sender")}</option>
              <option value="month">{uiText("Month")}</option>
              <option value="day">{uiText("Day")}</option>
              <option value="year">{uiText("Year")}</option>
              <option value="type">{uiText("File type")}</option>
              <option value="source">{uiText("Source")}</option>
              <option value="review_status">{uiText("Review status")}</option>
              <option value="thread">{uiText("Thread")}</option>
              <option value="custodian">{uiText("Custodian")}</option>
              <option value="privilege_status">
                {uiText("Privilege status")}
              </option>
              <option value="reviewer">{uiText("Assigned reviewer")}</option>
              <option value="tag">{uiText("Tag")}</option>
            </select>
          </label>
          <button
            className="button secondary compact"
            onClick={() => setDialog("export")}
            disabled={!canExport}
          >
            <Icon name="export" size={15} />
            {uiText("Export")}
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
                {item.key === "person_id"
                  ? uiText("Participant")
                  : label(item.key)}
                :{" "}
                {typeof item.value === "boolean"
                  ? item.value
                    ? uiText("Yes")
                    : uiText("No")
                  : item.key === "person_id"
                    ? person.data?.name ||
                      person.data?.email ||
                      uiText("Selected header address")
                    : [
                          "item_types",
                          "review_status",
                          "privilege_status",
                          "type",
                          "parser_state",
                        ].includes(item.key)
                      ? label(String(item.value))
                      : String(item.value)}
              </span>
              <Icon name="close" size={12} />
            </button>
          ))}
          <button
            className="clear-filters"
            onClick={() => update({ filters: {} })}
          >
            {uiText("Clear filters")}
          </button>
        </div>
      )}
      <ErrorBox error={error} retry={() => setVersion((value) => value + 1)} />
      <div
        className={`evidence-workbench ${selectedId ? "has-inspector" : ""}`}
      >
        <aside
          className={`filter-panel ${filtersOpen ? "open" : ""}`}
          aria-label={uiText("Evidence filters")}
        >
          <div className="filter-title">
            <strong>{uiText("Refine the record")}</strong>
            <Icon name="filter" size={16} />
          </div>
          <FilterSection title={uiText("Evidence type")}>
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
                      ? uiText("Archive / mailbox")
                      : type === "binary"
                        ? uiText("Other / unsupported")
                        : label(type)}
                  </span>
                  {bucket && <small>{number(bucket.count)}</small>}
                </label>
              );
            })}
          </FilterSection>
          <FilterSection title={uiText("Review status")}>
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
          <FilterSection title={uiText("Collection")}>
            <label className="filter-field">
              {uiText("Source")}
              <select
                value={((spec.filters.source_ids || []) as string[])[0] || ""}
                onChange={(event) =>
                  filter(
                    "source_ids",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">{uiText("All sources")}</option>
                {sources.data?.items.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              {uiText("Custodian")}
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
                <option value="">{uiText("All custodians")}</option>
                {custodians.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              {uiText("Sender")}
              <input
                value={String(spec.filters.sender || "")}
                onChange={(event) => filter("sender", event.target.value)}
                placeholder={uiText("Email address")}
              />
            </label>
            <label className="filter-field">
              {uiText("Recipient")}
              <input
                value={String(spec.filters.recipient || "")}
                onChange={(event) => filter("recipient", event.target.value)}
                placeholder={uiText("Address contains…")}
              />
            </label>
            <label className="filter-field">
              {uiText("Attachments")}
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
                <option value="">{uiText("With or without")}</option>
                <option value="true">{uiText("With attachments")}</option>
                <option value="false">{uiText("Without attachments")}</option>
              </select>
            </label>
            <ErrorBox error={sources.error || custodians.error} />
          </FilterSection>
          <FilterSection title={uiText("Date · UTC")}>
            <label className="filter-field">
              {uiText("Date field")}
              <select
                value={String(spec.filters.date_field || "sent_at")}
                onChange={(event) => filter("date_field", event.target.value)}
              >
                <option value="sent_at">{uiText("Source timestamp")}</option>
                <option value="imported_at">
                  {uiText("Imported timestamp")}
                </option>
              </select>
            </label>
            <label className="filter-field">
              {uiText("From")}
              <input
                type="date"
                value={String(spec.filters.date_from || "")}
                onChange={(event) => filter("date_from", event.target.value)}
              />
            </label>
            <label className="filter-field">
              {uiText("To")}
              <input
                type="date"
                value={String(spec.filters.date_to || "")}
                onChange={(event) => filter("date_to", event.target.value)}
              />
            </label>
            <label className="filter-field">
              {uiText("Timestamp availability")}
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
                <option value="">{uiText("Dated and undated")}</option>
                <option value="true">{uiText("Missing timestamp")}</option>
                <option value="false">{uiText("Has timestamp")}</option>
              </select>
            </label>
          </FilterSection>
          <FilterSection title={uiText("Review & processing")}>
            <label className="filter-field">
              {uiText("Privilege status")}
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
                <option value="">{uiText("All determinations")}</option>
                {["none", "suspected", "confirmed", "cleared"].map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              {uiText("Processing state")}
              <select
                value={((spec.filters.parser_state || []) as string[])[0] || ""}
                onChange={(event) =>
                  filter(
                    "parser_state",
                    event.target.value ? [event.target.value] : [],
                  )
                }
              >
                <option value="">{uiText("All processing states")}</option>
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
              {uiText("Assigned reviewer")}
              <select
                value={String(spec.filters.assigned_to || "")}
                onChange={(event) => filter("assigned_to", event.target.value)}
              >
                <option value="">{uiText("All reviewers")}</option>
                {members.data?.items.map((item) => (
                  <option key={item.user_id} value={item.user_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="filter-field">
              {uiText("Tag")}
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
                placeholder={uiText("Exact tags, comma separated")}
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
              <span>{uiText("Bookmarked only")}</span>
            </label>
            <ErrorBox error={members.error} />
          </FilterSection>
          <FilterSection title={uiText("Saved searches")}>
            {saved.data?.items.length ? (
              <select
                aria-label={uiText("Load saved search")}
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
                <option value="">{uiText("Choose a saved search")}</option>
                {saved.data.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            ) : (
              <p className="muted">
                {uiText("Save a query to return to it later.")}
              </p>
            )}
            <ErrorBox error={saved.error} />
          </FilterSection>
          <div className="filter-footnote">
            <Icon name="shield" size={16} />
            <p>
              {uiText(
                "Search is limited to the evidence you can access in this matter.",
              )}
            </p>
          </div>
        </aside>
        <section
          className="results-panel"
          aria-label={uiText("Search results")}
        >
          {spec.group_by && result?.groups.length ? (
            <div className="group-summary">
              <div>
                <strong>
                  {uiText("{0} groups", { "0": label(spec.group_by) })}
                </strong>
                <small>
                  {uiText("Full-scope counts · up to 200 returned groups")}
                </small>
              </div>
              <div className="group-chips">
                {result.groups.map((item) => (
                  <button
                    key={item.key}
                    disabled={
                      !item.key ||
                      item.key === "Unknown" ||
                      item.key === "Untagged" ||
                      importDateScope
                    }
                    title={
                      !item.key || item.key === "Unknown"
                        ? uiText(
                            "Missing metadata cannot be drilled down in this preview. These items remain in the evidence results.",
                          )
                        : importDateScope
                          ? `${uiText("Date field")}: ${uiText("Imported timestamp")}`
                          : undefined
                    }
                    onClick={() => {
                      if (dateGrouping) {
                        const filters = dateBucketFilters(
                          spec.filters,
                          item.key,
                          spec.group_by!,
                        );
                        if (filters) update({ filters });
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
                            : [
                                  "type",
                                  "review_status",
                                  "privilege_status",
                                ].includes(spec.group_by || "")
                              ? label(item.key)
                              : item.key || uiText("Not recorded")}
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
                <strong>{number(selected.length)}</strong>{" "}
                {" " + uiText("selected on this page")}
              </span>
              <div>
                <button
                  className="button secondary compact"
                  disabled={!canReview}
                  onClick={() => setDialog("bulk")}
                >
                  {uiText("Review selected")}
                </button>
                <button
                  className="button secondary compact"
                  onClick={() => setDialog("set")}
                  disabled={!canReview}
                >
                  {uiText("Save review set")}
                </button>
                {can(matter.role, "manage") && (
                  <button
                    className="button secondary compact"
                    onClick={() => setDialog("assign")}
                  >
                    {uiText("Assign selected")}
                  </button>
                )}
                <button
                  className="icon-button"
                  aria-label={uiText("Clear selection")}
                  onClick={() => setSelected([])}
                >
                  <Icon name="close" size={15} />
                </button>
              </div>
            </div>
          )}
          <div className={`evidence-table-wrap ${loading ? "is-loading" : ""}`}>
            {loading || (!result && !error) ? (
              <Loading text={uiText("Searching the evidence record…")} />
            ) : !result?.items.length ? (
              <Empty
                icon="search"
                title={
                  spec.query || activeFilters.length
                    ? uiText("No evidence matches this scope")
                    : uiText("Your record is ready to begin")
                }
                text={
                  spec.query || activeFilters.length
                    ? uiText(
                        "Try a different query or widen your filters. Unprocessed sources remain in the import report.",
                      )
                    : uiText(
                        "Import a source to preserve originals and make their extracted content searchable.",
                      )
                }
              >
                {!spec.query && !activeFilters.length && (
                  <Link
                    className="button primary"
                    href={`/app/matters/${matter.id}/sources`}
                  >
                    {uiText("Import evidence")}
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
                        aria-label={uiText("Select all visible evidence")}
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
                    <th>{uiText("Evidence")}</th>
                    <th>
                      {uiText("Date · {0}", { "0": getDisplayTimeZone() })}
                    </th>
                    <th>{uiText("Status")}</th>
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
                          aria-label={uiText("Select {0}", { "0": item.title })}
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
                          disabled={
                            inspectorBlocked && selectedId !== item.evidence_id
                          }
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
                                  {uiText("Attachments")}
                                </span>
                              )}
                            </span>
                            <span className="evidence-snippet">
                              {item.snippet ||
                                uiText("No text snippet available")}
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
                              value={item.privilege_status}
                              text={`${uiText("Privilege status")}: ${label(item.privilege_status)}`}
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
                ? uiText("Page {0} · {1} shown of {2}", {
                    "0": history.length + 1,
                    "1": number(result.items.length),
                    "2": number(result.total_hits),
                  })
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
                  uiText("See source inventory for full processing coverage.")}
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
            navigationBlocked={setInspectorBlocked}
            navigation={
              selectedPosition >= 0 && result
                ? {
                    position: selectedPosition + 1,
                    count: result.items.length,
                    previous:
                      result.items[selectedPosition - 1]?.evidence_id || null,
                    next:
                      result.items[selectedPosition + 1]?.evidence_id || null,
                  }
                : undefined
            }
          />
        ) : (
          <aside className="inspector-placeholder">
            <span className="empty-icon">
              <Icon name="file" size={25} />
            </span>
            <h3>{uiText("Read the record.")}</h3>
            <p>
              {uiText(
                "Open an evidence item to inspect its source, extracted text and review history.",
              )}
            </p>
            <div>
              <Icon name="shield" size={16} />
              <span>{uiText("Originals stay preserved.")}</span>
            </div>
          </aside>
        )}
      </div>
      {dialog && !routeChanged && (
        <ExplorerActionModal
          key={JSON.stringify([matter.id, dialog, selected, spec])}
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
  navigation,
  navigationBlocked,
}: {
  caseId: string;
  id: string;
  canReview: boolean;
  canPrivilege: boolean;
  canManage?: boolean;
  close: () => void;
  changed: () => void;
  open: (id: string) => void;
  navigation?: {
    position: number;
    count: number;
    previous: string | null;
    next: string | null;
  };
  navigationBlocked?: (blocked: boolean) => void;
}) {
  const path = usePathname(),
    params = useSearchParams(),
    versionRouter = useRouter(),
    version = path.endsWith(`/evidence/${id}`) ? params.get("version") : null;
  const canReview = allowReview && !version,
    canManage = allowManage && !version;
  const reviewScope = `${caseId}:${id}:${version || "current"}`;
  const reviewGeneration = useRef({ scope: reviewScope, revision: 0 });
  if (reviewGeneration.current.scope !== reviewScope)
    reviewGeneration.current = {
      scope: reviewScope,
      revision: reviewGeneration.current.revision + 1,
    };
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
    [message, setMessage] = useState<InterfaceMessage>(""),
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
  const inspectorTabs: [string, MessageKey][] = [
    ["content", "Content"],
    ["metadata", "Source"],
    ["review", "Review"],
  ];
  if (!version) inspectorTabs.push(["investigate", "Investigate"]);
  if (data?.type === "email") inspectorTabs.push(["thread", "Thread"]);
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
    const submittedGeneration = reviewGeneration.current.revision;
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
      if (
        activeReviewScope.current !== submittedScope ||
        reviewGeneration.current.revision !== submittedGeneration
      )
        return;
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
      if (
        activeReviewScope.current === submittedScope &&
        reviewGeneration.current.revision === submittedGeneration
      ) {
        setError(error);
        detail.refresh();
      }
    } finally {
      if (
        activeReviewScope.current === submittedScope &&
        reviewGeneration.current.revision === submittedGeneration
      )
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
  const unsaved = Boolean(
    note.trim() || (tagDraft.current.dirty && tags !== data?.tags.join(", ")),
  );
  useEffect(() => {
    navigationBlocked?.(busy || unsaved);
    return () => navigationBlocked?.(false);
  }, [busy, unsaved, navigationBlocked]);
  return (
    <aside
      className="evidence-inspector"
      aria-label={uiText("Evidence inspector")}
    >
      <div className="inspector-top">
        <span className="eyebrow">{uiText("EVIDENCE INSPECTOR")}</span>
        <button
          className="icon-button"
          aria-label={uiText("Close evidence inspector")}
          disabled={busy || unsaved}
          onClick={close}
        >
          <Icon name="close" size={18} />
        </button>
      </div>
      {navigation && (
        <nav
          className={navigationStyles.navigation}
          aria-label={uiText("Navigate visible evidence")}
        >
          <button
            className="button secondary compact"
            type="button"
            disabled={!navigation.previous || busy || unsaved}
            onClick={() => navigation.previous && open(navigation.previous)}
          >
            <Icon name="back" size={14} /> {" " + uiText("Previous item")}
          </button>
          <span>
            {uiText("Item {0} of {1} on this page", {
              "0": navigation.position,
              "1": navigation.count,
            })}
          </span>
          <button
            className="button secondary compact"
            type="button"
            disabled={!navigation.next || busy || unsaved}
            onClick={() => navigation.next && open(navigation.next)}
          >
            {uiText("Next item") + " "}
            <Icon name="arrow" size={14} />
          </button>
          {unsaved && (
            <small>
              {uiText(
                "Save or clear your unsaved tags and note before moving to another item.",
              )}
            </small>
          )}
        </nav>
      )}
      <ErrorBox
        error={detail.error || historical.error}
        retry={() => {
          detail.refresh();
          historical.refresh();
        }}
      />
      {(detail.loading || historical.loading) && !data ? (
        <Loading text={uiText("Opening evidence…")} />
      ) : (
        data && (
          <>
            {version && (
              <div className="notice amber" role="status">
                <Icon name="lock" size={17} />
                <span>
                  {historical.data?.superseded
                    ? uiText(
                        "Superseded extraction v{0}; the current version is v{1}.",
                        { "0": version, "1": historical.data.current_version },
                      )
                    : uiText("Version-specific extraction v{0}.", {
                        "0": version,
                      })}{" "}
                  {uiText(
                    "This view is read-only. Current review and production use the latest extraction.",
                  )}{" "}
                  <Link
                    className="text-link"
                    href={`/app/matters/${caseId}/evidence/${id}`}
                  >
                    {uiText("Open current evidence")}
                  </Link>
                </span>
              </div>
            )}
            <label className="inspector-version-select">
              {uiText("Extracted text version")}
              <select
                value={version || "current"}
                aria-label={uiText("Extracted text version")}
                disabled={busy || unsaved}
                onChange={(event) =>
                  versionRouter.push(
                    `/app/matters/${caseId}/evidence/${id}${event.target.value === "current" ? "" : `?version=${event.target.value}`}`,
                  )
                }
              >
                <option value="current">
                  {uiText("Current extraction{0}", {
                    "0": versions.data?.current_version
                      ? ` ${uiText("· v{0}", { "0": versions.data.current_version })}`
                      : "",
                  })}
                </option>
                {version &&
                  !versions.data?.items.some(
                    (item) => String(item.version) === version,
                  ) && (
                    <option value={version}>
                      {uiText("Cited extraction v{0}", { "0": version })}
                    </option>
                  )}
                {versions.data?.items.map((item) => (
                  <option key={item.version} value={String(item.version)}>
                    {uiText("v{0} · {1}", {
                      "0": item.version,
                      "1": item.current
                        ? uiText("current")
                        : uiText("superseded"),
                    })}
                  </option>
                ))}
              </select>
              {versions.data?.before_version && (
                <small>
                  {uiText(
                    "Showing the latest 50 versions. Older versions remain addressable by their exact version link.",
                  )}
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
                  {uiText("Original")}
                </a>
                {canReview && (
                  <Link
                    className="button secondary compact"
                    href={`/app/matters/${caseId}/productions?evidence_id=${id}`}
                    aria-disabled={busy || unsaved}
                    onClick={(event) => {
                      if (busy || unsaved) event.preventDefault();
                    }}
                  >
                    {uiText("Redact")}
                  </Link>
                )}
                <button
                  className={`icon-button ${data.bookmarked ? "starred" : ""}`}
                  disabled={busy || !canReview}
                  aria-label={
                    data.bookmarked
                      ? uiText("Remove bookmark")
                      : uiText("Bookmark evidence")
                  }
                  onClick={() => void review({ bookmarked: !data.bookmarked })}
                >
                  <Icon name="star" size={18} />
                </button>
                <button
                  className="button ghost compact"
                  disabled={busy}
                  onClick={async () => {
                    const submittedGeneration =
                      reviewGeneration.current.revision;
                    const submittedScope = reviewScope;
                    setBusy(true);
                    setError(null);
                    try {
                      const result = await post<{
                        valid: boolean;
                        expected_sha256: string;
                        actual_sha256: string;
                      }>(`/cases/${caseId}/evidence/${id}/verify`);
                      if (
                        activeReviewScope.current === submittedScope &&
                        reviewGeneration.current.revision ===
                          submittedGeneration
                      )
                        setVerified(result);
                    } catch (error) {
                      if (
                        activeReviewScope.current === submittedScope &&
                        reviewGeneration.current.revision ===
                          submittedGeneration
                      )
                        setError(error);
                    } finally {
                      if (
                        activeReviewScope.current === submittedScope &&
                        reviewGeneration.current.revision ===
                          submittedGeneration
                      )
                        setBusy(false);
                    }
                  }}
                >
                  <Icon name="shield" size={15} />
                  {uiText("Verify")}
                </button>
              </div>
            </div>
            {data.integrity_status === "failed" && (
              <div className="notice red" role="alert">
                <Icon name="alert" size={17} />
                <span>
                  {uiText(
                    "Original integrity verification failed. Download is blocked; investigate the preserved source.",
                  )}
                </span>
              </div>
            )}
            {data.parser_error && (
              <div className="notice amber">
                <Icon name="alert" size={17} />
                <span>
                  {uiText(
                    "Extraction limitation: {0}. Review the original and import report for full coverage.",
                    { "0": label(data.parser_error) },
                  )}
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
                    ? uiText("Original hash verified.")
                    : uiText(
                        "Original hash mismatch. Source integrity requires investigation.",
                      )}
                </span>
              </div>
            )}
            <div
              className="inspector-tabs"
              role="tablist"
              aria-label={uiText("Evidence details")}
            >
              {inspectorTabs.map(([key, title]) => (
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
                    const keys = inspectorTabs.map(([key]) => key);
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
                  {uiText(title)}
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
                  {uiText(message)}
                </div>
              )}
              {tab === "content" ? (
                <>
                  {data.email && (
                    <dl className="email-envelope">
                      <div>
                        <dt>{uiText("From")}</dt>
                        <dd>{people(data.email.from)}</dd>
                      </div>
                      <div>
                        <dt>{uiText("To")}</dt>
                        <dd>{people(data.email.to)}</dd>
                      </div>
                      {people(data.email.cc) !== "" &&
                        people(data.email.cc) !== "—" && (
                          <div>
                            <dt>{uiText("CC")}</dt>
                            <dd>{people(data.email.cc)}</dd>
                          </div>
                        )}
                      <div>
                        <dt>{uiText("Sent")}</dt>
                        <dd>{date(data.date_utc, true)}</dd>
                      </div>
                      {!["", "—"].includes(people(data.email.bcc)) && (
                        <div>
                          <dt>{uiText("BCC")}</dt>
                          <dd>{people(data.email.bcc)}</dd>
                        </div>
                      )}
                      {!["", "—"].includes(people(data.email.reply_to)) && (
                        <div>
                          <dt>{uiText("Reply-To")}</dt>
                          <dd>{people(data.email.reply_to)}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                  <div className="text-viewer-heading">
                    <span>
                      {data.type === "pdf"
                        ? uiText("EXTRACTED DOCUMENT TEXT")
                        : uiText("EXTRACTED CONTENT")}
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
                            {uiText("{0} · v{1}", {
                              "0": span.page
                                ? uiText("Page {0}", { "0": span.page })
                                : uiText("Chars {0}–{1}", {
                                    "0": span.char_start,
                                    "1": span.char_end,
                                  }),
                              "1": span.artifact_version,
                            })}
                          </span>
                          <p>{span.text}</p>
                          <button
                            className="citation-copy"
                            onClick={async () => {
                              try {
                                await navigator.clipboard.writeText(
                                  `${data.evidence_id} · extraction v${span.artifact_version} · ${span.page ? `page ${span.page}` : `chars ${span.char_start}-${span.char_end}`} · ${span.span_id || span.id}`,
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
                            {uiText("Copy source reference")}
                          </button>
                          <button
                            className="citation-copy"
                            type="button"
                            onClick={async () => {
                              const sourceUrl = `${window.location.origin}/app/matters/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(id)}?version=${span.artifact_version}#span-${encodeURIComponent(span.span_id || span.id)}`;
                              try {
                                await navigator.clipboard.writeText(sourceUrl);
                                setMessage(
                                  "Version-specific source link copied. Access requires matter permission.",
                                );
                              } catch {
                                setMessage(
                                  uiMessage(
                                    "Copy this version-specific source link: {0}",
                                    { "0": sourceUrl },
                                  ),
                                );
                              }
                            }}
                          >
                            <Icon name="copy" size={12} />{" "}
                            {" " + uiText("Copy source link")}
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
                              {uiText("Note this location")}
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
                      {uiText(
                        "No extracted text is available. Review the original and processing report.",
                      )}
                    </div>
                  )}
                  {data.attachments?.length > 0 && (
                    <div className="attachment-list">
                      <h3>
                        {uiText("Attachment family")}{" "}
                        <span className="count-chip">
                          {data.attachments.length}
                        </span>
                      </h3>
                      {data.attachments.map((item) => (
                        <button
                          key={item.evidence_id}
                          disabled={busy || unsaved}
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
                      disabled={busy || unsaved}
                      onClick={() =>
                        open((data.parent_id || data.parent_item_id)!)
                      }
                    >
                      <Icon name="back" size={15} />
                      {uiText("Parent evidence")}
                    </button>
                  )}
                  {data.email && (
                    <div className="raw-header-section">
                      <button
                        className="text-link"
                        onClick={() => setRaw((value) => !value)}
                      >
                        {raw
                          ? uiText("Hide original headers")
                          : uiText("Show original headers")}
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
                  <h3>{uiText("Source provenance")}</h3>
                  <dl className="metadata-list">
                    <Meta
                      title={uiText("Original filename")}
                      value={data.original_name}
                    />
                    <Meta title={uiText("Source")} value={data.source?.label} />
                    <Meta
                      title={uiText("Custodian")}
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
                    <Meta
                      title={uiText("Evidence ID")}
                      value={data.evidence_id}
                    />
                    <Meta
                      title={uiText("Preserved size")}
                      value={bytes(data.byte_size)}
                    />
                    <Meta
                      title={uiText("Integrity state")}
                      value={data.integrity_status}
                    />
                    <Meta
                      title={uiText("Processing state")}
                      value={data.parser_state}
                    />
                    <Meta
                      title={uiText("UTC timestamp")}
                      value={data.date_utc}
                    />
                    <Meta
                      title={uiText("Raw source time")}
                      value={data.email?.sent_at_raw || data.date_raw}
                    />
                    <Meta
                      title={uiText("Time zone provenance")}
                      value={
                        data.timezone_source || uiText("See original metadata")
                      }
                    />
                  </dl>
                  {data.metadata && Object.keys(data.metadata).length > 0 && (
                    <>
                      <h3>{uiText("Extraction metadata")}</h3>
                      {Boolean(data.metadata.ocr_quality) && (
                        <div className="notice amber">
                          <Icon name="alert" size={16} />
                          <span>
                            {uiText(
                              "OCR text and confidence scores require human verification against the source. They do not establish evidentiary accuracy.",
                            )}
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
                        <summary>{uiText("All parser metadata")}</summary>
                        <pre>{JSON.stringify(data.metadata, null, 2)}</pre>
                      </details>
                    </>
                  )}
                  <h3>{uiText("Original SHA-256")}</h3>
                  <code className="hash-block">{data.sha256}</code>
                  <p className="field-help">
                    {uiText(
                      "The hash identifies the exact original bytes, independently of extracted text.",
                    )}
                  </p>
                  {data.derived_artifacts?.length ? (
                    <>
                      <h3>{uiText("Derived artifacts")}</h3>
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
                      <h3>{uiText("Source locations")}</h3>
                      <div className="span-list">
                        {data.spans.map((span, i) => (
                          <div key={span.span_id || span.id || i}>
                            <strong>
                              {span.page
                                ? uiText("Page {0}", { "0": span.page })
                                : uiText("Characters {0}–{1}", {
                                    "0": span.char_start,
                                    "1": span.char_end,
                                  })}
                            </strong>
                            <small className="mono">
                              {span.span_id || span.id}
                            </small>
                            <small>
                              {uiText("Artifact version {0}", {
                                "0": span.artifact_version,
                              })}
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
                    <span className="eyebrow">{uiText("HUMAN REVIEW")}</span>
                    <Badge value={data.review_status} />
                  </div>
                  <h3>{uiText("Responsiveness")}</h3>
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
                  <h3>{uiText("Privilege review")}</h3>
                  <p className="field-help">
                    {uiText(
                      "Suspicion is a review flag. Confirmed privilege is a human decision and can block export.",
                    )}
                  </p>
                  <select
                    aria-label={uiText("Privilege review status")}
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
                    <option value="none">{uiText("No privilege flag")}</option>
                    <option value="suspected">
                      {uiText("Suspected · requires review")}
                    </option>
                    <option value="confirmed" disabled={!canPrivilege}>
                      {uiText("Confirmed by attorney")}
                    </option>
                    <option value="cleared" disabled={!canPrivilege}>
                      {uiText("Cleared by attorney")}
                    </option>
                  </select>
                  <h3>{uiText("Assigned reviewer")}</h3>
                  <label>
                    <span className="sr-only">
                      {uiText("Evidence assigned reviewer")}
                    </span>
                    <select
                      value={data.assigned_to || ""}
                      disabled={!canManage || busy}
                      onChange={(event) =>
                        void review({ assigned_to: event.target.value || null })
                      }
                    >
                      <option value="">{uiText("Unassigned")}</option>
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
                    {uiText(
                      "Matter leads and review managers can change direct allocation. Reviewers claim fixed snapshots from the review queue.",
                    )}
                  </p>
                  <h3>{uiText("Human tags")}</h3>
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
                        {uiText("Comma-separated evidence tags")}
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
                        placeholder={uiText("Payment approval, Key witness")}
                        disabled={!canReview}
                      />
                    </label>
                    <small className="field-help">
                      {uiText("Separate tags with a comma.")}
                    </small>
                    <button
                      className="button secondary compact"
                      disabled={busy || !canReview}
                    >
                      {uiText("Save tags")}
                    </button>
                  </form>
                  <h3>{uiText("Review note")}</h3>
                  <label>
                    {uiText("Source location")}
                    <select
                      value={noteSpan || ""}
                      onChange={(event) =>
                        setNoteSpan(event.target.value || null)
                      }
                      disabled={!canReview}
                    >
                      <option value="">
                        {uiText("General evidence note")}
                      </option>
                      {data.spans.map((span) => (
                        <option key={span.id} value={span.span_id || span.id}>
                          {span.page
                            ? uiText("Page {0}", { "0": span.page })
                            : uiText("Chars {0}–{1}", {
                                "0": span.char_start,
                                "1": span.char_end,
                              })}{" "}
                          · {span.span_id || span.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <form
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!note.trim()) return;
                      const submittedScope = reviewScope;
                      const submittedGeneration =
                        reviewGeneration.current.revision;
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
                        if (
                          activeReviewScope.current !== submittedScope ||
                          reviewGeneration.current.revision !==
                            submittedGeneration
                        )
                          return;
                        setNote("");
                        setNoteSpan(null);
                        detail.refresh();
                        setMessage("Note saved.");
                      } catch (error) {
                        if (
                          activeReviewScope.current === submittedScope &&
                          reviewGeneration.current.revision ===
                            submittedGeneration
                        )
                          setError(error);
                      } finally {
                        if (
                          activeReviewScope.current === submittedScope &&
                          reviewGeneration.current.revision ===
                            submittedGeneration
                        )
                          setBusy(false);
                      }
                    }}
                  >
                    <label>
                      <span className="sr-only">
                        {uiText("Evidence review note")}
                      </span>
                      <textarea
                        aria-label={uiText("Evidence review note")}
                        rows={3}
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder={uiText("Add a note for your review team…")}
                        required
                        disabled={busy || !canReview}
                      />
                    </label>
                    <button
                      className="button secondary compact"
                      disabled={busy || !canReview || !note.trim()}
                    >
                      {uiText("Add note")}
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
                              {uiText("Open anchored location")}
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {data.review_history?.length > 0 && (
                    <>
                      <h3>{uiText("Review history")}</h3>
                      <div className="notes-list">
                        {data.review_history.map((item) => (
                          <div key={item.id}>
                            <strong>
                              {item.review_status || item.changes?.review_status
                                ? label(
                                    (item.review_status ||
                                      item.changes?.review_status)!,
                                  )
                                : uiText("Review updated")}
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
                      {uiText(
                        "Your matter role allows reading this evidence. Review changes require additional permission.",
                      )}
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
      <dd>{value || uiText("Not recorded")}</dd>
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
  const live = useMountedRef();
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
  const titles: Record<typeof kind, MessageKey> = {
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
        const result = await post<{ id: string; state: string }>(
          `/cases/${caseId}/exports`,
          {
            format: form.get("format"),
            ...(selected.length
              ? { evidence_ids: selected }
              : { query_spec: { ...spec, cursor: null } }),
            reason: form.get("reason"),
            confirmed: form.get("confirmed") === "on",
          },
        );
        if (live.current) setDownload(result);
      } else if (live.current) done();
    } catch (error) {
      if (live.current) setError(error);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <Modal title={uiText(titles[kind])} close={close}>
      <ErrorBox error={error} />
      {download ? (
        <>
          <div className="notice green" role="status">
            <Icon name="check" />
            {uiText("Export") + " "}
            {label(download.state).toLowerCase()}.
          </div>
          <p className="muted">
            {uiText(
              "The server checked your permissions, evidence integrity and export holdbacks.",
            )}
          </p>
          {["completed", "ready"].includes(download.state.toLowerCase()) ? (
            <a
              className="button primary"
              href={`/api/v1/cases/${caseId}/exports/${download.id}/download`}
            >
              <Icon name="export" size={17} />
              {uiText("Download export")}
            </a>
          ) : (
            <Link
              href={`/app/matters/${caseId}/reports`}
              className="button primary"
            >
              {uiText("View export status")}
              <Icon name="arrow" size={16} />
            </Link>
          )}
        </>
      ) : (
        <form onSubmit={submit}>
          <p className="muted">
            {kind === "saved"
              ? uiText(
                  "Preserve this query, filters, sort and grouping so you can return to the same scope.",
                )
              : selected.length
                ? uiText("{0} explicitly selected evidence items.", {
                    "0": number(selected.length),
                  })
                : uiText(
                    "All evidence matching the current query and filters, across every page.",
                  )}
          </p>
          {["saved", "set", "assign"].includes(kind) && (
            <label>
              {uiText("Name")}
              <input
                name="name"
                required
                maxLength={200}
                placeholder={
                  kind === "saved"
                    ? uiText("Finance correspondence · Q2")
                    : uiText("First-pass review")
                }
              />
            </label>
          )}
          {kind === "assign" && (
            <>
              <ErrorBox error={members.error} />
              <label>
                {uiText("Assigned reviewer")}
                <select name="assignee_id" defaultValue="">
                  <option value="">
                    {uiText("Unassigned · available to claim")}
                  </option>
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
                {uiText("Assignment reason")}
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={3}
                />
              </label>
              <p className="field-help">
                {uiText(
                  "The selected items form a fixed snapshot. Items already reserved by another open assignment are rejected.",
                )}
              </p>
            </>
          )}
          {kind === "bulk" && (
            <>
              <label>
                {uiText("Review decision")}
                <select name="review_status">
                  <option value="needs_review">{uiText("Needs review")}</option>
                  <option value="responsive">{uiText("Responsive")}</option>
                  <option value="non_responsive">
                    {uiText("Non-responsive")}
                  </option>
                  <option value="unreviewed">{uiText("Unreviewed")}</option>
                </select>
              </label>
              <label>
                {uiText("Tags") + " "}
                <span className="optional">{uiText("optional")}</span>
                <input
                  name="tags"
                  placeholder={uiText("Comma-separated tags")}
                />
              </label>
            </>
          )}
          {kind === "export" && (
            <>
              <label>
                {uiText("Format")}
                <select name="format">
                  <option value="csv">
                    {uiText("CSV metadata + hash manifest")}
                  </option>
                  <option value="json">
                    {uiText("JSON metadata + hash manifest")}
                  </option>
                  <option value="zip">
                    {uiText("ZIP evidence package + manifest")}
                  </option>
                </select>
              </label>
              <label>
                {uiText("Purpose or reason")}
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  rows={3}
                  placeholder={uiText("Describe the purpose of this export")}
                />
              </label>
              <label className="checkbox-label">
                <input name="confirmed" type="checkbox" required />
                <span>
                  {uiText(
                    "I reviewed the evidence scope and am authorized to export it.",
                  )}
                </span>
              </label>
              <div className="notice amber">
                <Icon name="lock" size={17} />
                <span>
                  {uiText(
                    "Server privilege, review and integrity checks can block this export. Preview exports are limited to 20,000 items.",
                  )}
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
              {uiText("Cancel")}
            </button>
            <button className="button primary" disabled={busy}>
              {busy
                ? uiText("Saving…")
                : kind === "export"
                  ? uiText("Create export")
                  : kind === "bulk"
                    ? uiText("Save review decisions")
                    : uiText("Save")}
              <Icon name="arrow" size={16} />
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
