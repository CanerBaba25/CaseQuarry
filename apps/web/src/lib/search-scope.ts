import type { SearchSpec } from "./types";

const scalarFilters = [
  "person_id",
  "sender_person_id",
  "recipient_person_id",
  "thread_id",
  "parent_id",
  "assigned_to",
  "sender",
  "recipient",
  "date_from",
  "date_to",
  "date_field",
];
const arrayFilters: Record<string, string> = {
  type: "item_types",
  source_id: "source_ids",
  custodian_id: "custodian_ids",
  review_status: "review_status",
  privilege_status: "privilege_status",
  parser_state: "parser_state",
  tag: "tags",
};

export function filtersFromParams(
  params: URLSearchParams,
): SearchSpec["filters"] {
  const filters: SearchSpec["filters"] = {};
  for (const key of scalarFilters)
    if (params.get(key)) filters[key] = params.get(key);
  for (const [key, field] of Object.entries(arrayFilters))
    if (params.getAll(key).length) filters[field] = params.getAll(key);
  for (const key of ["missing_date", "has_attachment", "bookmarked"]) {
    if (["true", "false"].includes(params.get(key) || ""))
      filters[key] = params.get(key) === "true";
  }
  return filters;
}

export function evidenceUrl(
  caseId: string,
  filters: SearchSpec["filters"],
  emailOnly = false,
): string {
  const params = new URLSearchParams();
  for (const key of scalarFilters)
    if (filters[key]) params.set(key, String(filters[key]));
  for (const [key, field] of Object.entries(arrayFilters)) {
    const values = filters[field];
    if (Array.isArray(values))
      for (const value of values) params.append(key, String(value));
  }
  for (const key of ["missing_date", "has_attachment", "bookmarked"])
    if (typeof filters[key] === "boolean")
      params.set(key, String(filters[key]));
  return `/app/matters/${caseId}/${emailOnly ? "emails" : "explorer"}${params.size ? `?${params}` : ""}`;
}

export function bucketRange(key: string, grouping: string) {
  const first =
    grouping === "year"
      ? `${key}-01-01`
      : grouping === "month"
        ? `${key}-01`
        : key;
  const last = new Date(`${first}T00:00:00Z`);
  if (Number.isNaN(last.getTime())) return {};
  if (grouping === "year") last.setUTCFullYear(last.getUTCFullYear() + 1);
  else if (grouping === "month") last.setUTCMonth(last.getUTCMonth() + 1);
  else last.setUTCDate(last.getUTCDate() + 1);
  last.setUTCDate(last.getUTCDate() - 1);
  return { date_from: first, date_to: last.toISOString().slice(0, 10) };
}
