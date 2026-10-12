"use client";

import Link from "next/link";
import { useState } from "react";
import { number } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { bucketRange, evidenceUrl } from "@/lib/search-scope";
import type { Matter, Source } from "@/lib/types";
import { Empty, ErrorBox, Icon, Loading } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";

export type CommunicationScope = {
  date_from?: string;
  date_to?: string;
  source_id?: string;
  custodian_id?: string;
};
export function scopeParams(scope: CommunicationScope) {
  return new URLSearchParams(
    Object.entries(scope).filter(([, value]) => Boolean(value)) as [
      string,
      string,
    ][],
  ).toString();
}
export function scopeFilters(scope: CommunicationScope) {
  return {
    ...(scope.date_from ? { date_from: scope.date_from } : {}),
    ...(scope.date_to ? { date_to: scope.date_to } : {}),
    ...(scope.source_id ? { source_ids: [scope.source_id] } : {}),
    ...(scope.custodian_id ? { custodian_ids: [scope.custodian_id] } : {}),
  };
}

export function CommunicationScopeForm({
  matter,
  apply,
}: {
  matter: Matter;
  apply: (scope: CommunicationScope) => void;
}) {
  const sources = useResource<{ items: Source[] }>(
    `/cases/${matter.id}/sources`,
  );
  const custodians = useResource<{
    items: { id: string; display_name: string }[];
  }>(`/cases/${matter.id}/custodians`);
  return (
    <section className="panel scope-panel">
      <form
        className="scope-form"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          apply(Object.fromEntries(data) as CommunicationScope);
        }}
      >
        <label>
          From · UTC
          <input type="date" name="date_from" />
        </label>
        <label>
          Through · UTC
          <input type="date" name="date_to" />
        </label>
        <label>
          Source
          <select name="source_id">
            <option value="">All sources</option>
            {sources.data?.items.map((source) => (
              <option key={source.id} value={source.id}>
                {source.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Custodian
          <select name="custodian_id">
            <option value="">All custodians</option>
            {custodians.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        <button className="button primary compact">
          <Icon name="filter" size={16} />
          Apply scope
        </button>
        <button
          className="button ghost compact"
          type="reset"
          onClick={() => apply({})}
        >
          Reset
        </button>
      </form>
      <ErrorBox error={sources.error || custodians.error} />
    </section>
  );
}

type Traffic = {
  items: { key: string; count: number; unique_messages: number }[];
  group_by: string;
  timezone: string;
  missing_date_count: number;
  truncated: boolean;
  count_basis: string;
};
export default function CommunicationAnalytics({ matter }: { matter: Matter }) {
  const [grouping, setGrouping] = useState("day"),
    [scope, setScope] = useState<CommunicationScope>({}),
    [page, setPage] = useState(0);
  const resource = useResource<Traffic>(
    `/cases/${matter.id}/analytics/traffic?group_by=${grouping}&${scopeParams(scope)}`,
  );
  const items = resource.data?.items || [],
    maximum = Math.max(1, ...items.map((item) => item.count));
  const selectedFilters = scopeFilters(scope);
  const link = (key: string) =>
    evidenceUrl(
      matter.id,
      {
        ...selectedFilters,
        ...bucketRange(key, grouping),
        item_types: ["email"],
      },
      true,
    );
  return (
    <>
      <PageHeading
        eyebrow="EMAIL ANALYTICS"
        title="Follow the volume."
        text="Source-backed traffic aggregates with exact message scopes. Every chart respects this matter’s access and preserves duplicate source occurrences."
      >
        <Link
          className="button secondary"
          href={evidenceUrl(matter.id, selectedFilters, true)}
        >
          <Icon name="email" size={17} />
          Open email scope
        </Link>
      </PageHeading>
      <CommunicationScopeForm
        matter={matter}
        apply={(value) => {
          setScope(value);
          setPage(0);
        }}
      />
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading ? (
        <Loading text="Aggregating collected email traffic…" />
      ) : (
        resource.data && (
          <>
            <div className="metrics-grid analytics-metrics">
              <div className="metric-card">
                <span>Returned dated occurrences</span>
                <strong>
                  {number(items.reduce((count, item) => count + item.count, 0))}
                </strong>
                <small>
                  {resource.data.truncated
                    ? "Returned buckets only; additional dates omitted"
                    : "All matching dated email occurrences"}
                </small>
              </div>
              <div className="metric-card">
                <span>Undated email occurrences</span>
                <strong>{number(resource.data.missing_date_count)}</strong>
                <Link
                  href={evidenceUrl(
                    matter.id,
                    {
                      ...selectedFilters,
                      date_from: null,
                      date_to: null,
                      missing_date: true,
                    },
                    true,
                  )}
                >
                  Inspect missing timestamps <Icon name="arrow" size={13} />
                </Link>
              </div>
              <div className="metric-card">
                <span>Returned UTC periods</span>
                <strong>{number(items.length)}</strong>
                <small>
                  {resource.data.truncated
                    ? "First 500 chronological periods"
                    : "Database aggregate; no inferred dates"}
                </small>
              </div>
            </div>
            <div className="notice subtle">
              <Icon name="timeline" size={17} />
              <span>
                Date-only boundaries include the selected end day in UTC.
                Undated emails in this source/custodian scope cannot be assigned
                to any date range. Unique originals count byte-exact message
                objects separately.
              </span>
            </div>
            <section className="panel traffic-panel">
              <div className="section-heading">
                <div>
                  <h2>Collected email traffic</h2>
                  <p className="muted">
                    Open a period to inspect its dated messages.
                  </p>
                </div>
                <label className="inline-select">
                  Period
                  <select
                    aria-label="Traffic period"
                    value={grouping}
                    onChange={(event) => {
                      setGrouping(event.target.value);
                      setPage(0);
                    }}
                  >
                    <option value="day">Day</option>
                    <option value="month">Month</option>
                    <option value="year">Year</option>
                  </select>
                </label>
              </div>
              {!items.length ? (
                <Empty
                  icon="timeline"
                  title="No dated emails in this scope"
                  text="Widen the collection or date filters. Undated records remain available separately."
                />
              ) : (
                <>
                  <div
                    className="traffic-chart"
                    role="group"
                    aria-label="UTC traffic chart"
                  >
                    {items.slice(page * 50, (page + 1) * 50).map((item) => (
                      <Link
                        key={item.key}
                        href={link(item.key)}
                        className="traffic-bar"
                        aria-label={`${item.key}: ${number(item.count)} occurrences, ${number(item.unique_messages)} unique originals. Open messages.`}
                        title={`${item.key}: ${number(item.count)} occurrences`}
                      >
                        <span className="traffic-bar-track">
                          <span
                            style={{
                              height: `${Math.max(2, (item.count / maximum) * 100)}%`,
                            }}
                          />
                        </span>
                        <small>{item.key}</small>
                      </Link>
                    ))}
                  </div>
                  <div className="table-wrap">
                    <table>
                      <caption className="sr-only">
                        Exact database counts for the displayed UTC periods
                      </caption>
                      <thead>
                        <tr>
                          <th>UTC period</th>
                          <th>Source occurrences</th>
                          <th>Unique original messages</th>
                          <th>
                            <span className="sr-only">Evidence scope</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.slice(page * 50, (page + 1) * 50).map((item) => (
                          <tr key={item.key}>
                            <td>{item.key}</td>
                            <td>
                              <strong>{number(item.count)}</strong>
                            </td>
                            <td>{number(item.unique_messages)}</td>
                            <td>
                              <Link className="text-link" href={link(item.key)}>
                                Open messages <Icon name="arrow" size={14} />
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination
                    text={`Periods ${page * 50 + 1}–${Math.min((page + 1) * 50, items.length)} of ${number(items.length)} returned`}
                    previous={page ? () => setPage(page - 1) : undefined}
                    next={
                      (page + 1) * 50 < items.length
                        ? () => setPage(page + 1)
                        : undefined
                    }
                  />
                </>
              )}
            </section>
          </>
        )
      )}
    </>
  );
}
