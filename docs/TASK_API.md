# Task API

All routes below use `/api/v1`. Authentication is required. Cookie-authenticated mutations also require `X-CSRF-Token`. Task access follows current firm and matter membership; firm administration alone does not grant matter access. Active matter leads, attorneys, review managers and reviewers can create or edit tasks. Other valid matter roles can read them. Archived matters remain readable; task edits require restoring the matter first.

## Task details and edits

`GET /cases/{case_id}/tasks` returns a bounded, signed-cursor page. `GET /cases/{case_id}/tasks/{task_id}` returns the current task, including its `description`. Lists omit description bodies. Both representations include `id`, `case_id`, `title`, `state`, `priority`, `assigned_to`, `created_by`, `created_at`, `updated_at`, `version` and nullable `due_date`. Detail, create and update responses also include `server_today` and `time_zone`; task list responses include these fields alongside `items` and `next_cursor`.

Create a task with `POST /cases/{case_id}/tasks`:

```json
{
  "title": "Review correspondence",
  "description": "Check the cited messages before completing review.",
  "priority": "high",
  "assigned_to": "member-user-id",
  "due_date": "2031-02-28"
}
```

The title is required and limited to 300 characters. Description is optional, defaults to an empty string and is limited to 10,000 characters. Neither text field may contain embedded null characters. Priority is `low`, `normal`, `high` or `urgent`, defaulting to `normal`. Assignment is optional; a supplied assignee must be an active user with a valid role in the same matter. New tasks have state `open` and version `1`.

Every `PATCH /cases/{case_id}/tasks/{task_id}` must include the positive integer version obtained from the latest task response:

```json
{
  "expected_version": 1,
  "state": "in_progress",
  "description": "Review the new attachment as well."
}
```

Editable fields are `title`, `description`, `state`, `priority`, `assigned_to` and `due_date`. Valid states are `open`, `in_progress`, `done` and `cancelled`. Set `assigned_to` or `due_date` to `null` to clear them; clear description with `""`. Title, description, state and priority cannot be null. A request must include at least one editable field. Successful edits increment `version`, set `updated_at` and record the change in the audit chain.

Missing version returns HTTP 409 with `TASK_VERSION_REQUIRED`. An outdated version returns HTTP 409 with `TASK_VERSION_CONFLICT`; the stale request changes nothing. Retain the user's draft, reload the current task, compare the changes and ask them to save against the new version. Do not silently retry a stale draft with a newly fetched version. Existing clients must refresh after upgrading to this API.

The CLI reads the same authorized task details and sends the supplied JSON unchanged:

```text
cq --output json task show TASK_ID --case CASE_ID
cq --output json task update TASK_ID --case CASE_ID --body task-edit.json
cq --output json --limit 20 task list --case CASE_ID
cq --output json --limit 20 --cursor NEXT_CURSOR task list --case CASE_ID
cq --output table --limit 20 task worklist --priority urgent --sort priority
cq --output json task worklist --query "attachment review" --state in_progress
```

Create `task-edit.json` with the returned `version` as `expected_version` and the fields to change, as in the PATCH example above. A stale update exits with code 5 and preserves the server's `TASK_VERSION_CONFLICT` diagnostic. The CLI does not fetch a newer version or retry automatically. The equivalent detail request is `cq api request GET /cases/CASE_ID/tasks/TASK_ID`.

For task lists, pass the response's `next_cursor` unchanged with the same `--limit` to read the next page. Start again without a cursor when the server reports that the task list changed.

## My work

`GET /worklist` returns active tasks assigned to the current user across currently accessible, unarchived matters. Unassigned tasks, other users' assignments, completed/cancelled tasks and inaccessible matters are excluded. Invalid or revoked membership and inactive accounts do not contribute rows or counts.

Parameters:

| Parameter  | Values                                                                 | Default                    |
| ---------- | ---------------------------------------------------------------------- | -------------------------- |
| `state`    | `all`, `open`, `in_progress`                                           | `all` (both active states) |
| `due`      | `all`, `overdue`, `upcoming`, `no_due`                                 | `all`                      |
| `priority` | `all`, `low`, `normal`, `high`, `urgent`                               | `all`                      |
| `sort`     | `due`, `priority`                                                      | `due`                      |
| `q`        | Literal, case-insensitive task-title substring, at most 200 characters | Empty                      |
| `limit`    | 1–100                                                                  | 20                         |
| `cursor`   | Signed `next_cursor` from the same scope                               | Omitted                    |

The response includes `items`, `next_cursor`, `limit`, `state`, `due`, `q`, `priority`, `sort`, `user_id`, `server_today`, `time_zone`, `state_counts`, `priority_counts` and `summary`. Each item contains task metadata plus `matter: {id, matter_number, title, role}`. The default order is nearest due date, undated tasks last, then stable matter/task IDs. Priority order places urgent, high, normal and low tasks first, then applies the same deadline order within each priority. Search trims surrounding whitespace; `%`, `_` and backslashes remain literal. Embedded null characters return HTTP 422.

`state_counts: {all, open, in_progress}` counts visible active assignments matching the title query, independently of status, priority, deadline filter and page. `priority_counts: {all, low, normal, high, urgent}` additionally applies the selected status, independently of priority, deadline filter and page. `summary: {total, overdue, upcoming, no_due}` additionally applies the selected priority, independently of deadline filter and page. Page rows apply all filters. Counts and rows use one authorized database snapshot. Summary total can exceed the sum of deadline buckets because dates beyond the upcoming window are included in total.

The CLI's cross-matter `task worklist` accepts the corresponding `--state`, `--due`, `--priority`, `--sort` and `--query` options plus global `--limit`/`--cursor`. It rejects `--case`; use `task list --case CASE_ID` for one matter. JSON output preserves the complete server response; table output shows task title, priority, status, deadline, matter and exact ID.

Case matching follows the PostgreSQL database's Unicode collation and lowercase
rules; it does not apply accent removal or language-specific stemming.

Deadlines are manually entered calendar dates, not court deadline calculations. `server_today` is today's date in the user's saved IANA `time_zone`. Overdue means before that date; upcoming includes today through seven days later; no due means null. Date-only values do not shift when the user's timezone changes. Timestamp fields remain ISO timestamps and can be displayed in the saved timezone.

## Cursor recovery and upgrade

Cursors are bound to user, firm, filters, sort, timezone and local day. Changing that scope requires a new first-page request. Invalid scope returns HTTP 422 with `WORKLIST_CURSOR_INVALID` or `TASK_CURSOR_INVALID`. Version 0.6.0 replaces older worklist cursor formats; start from page one after upgrading.

New visible assignments, title/priority/deadline/assignment changes and access changes invalidate existing My work cursors with HTTP 409 `WORKLIST_CHANGED`. Status changes also invalidate status-filtered cursors. Completing a task can leave an all-active cursor usable, but clients should restart pagination after any mutation so counts and visible rows reflect the new state. Restart from page one on `WORKLIST_CHANGED`; do not append old pages to the refreshed list.

Matter task cursors also return HTTP 409 `TASK_LIST_CHANGED` when any task is created in that matter while paging, including unassigned tasks. Clear accumulated pages and restart the task list; the timestamp snapshot alone cannot safely exclude transactions that started before page one and committed later.

Migration `0007_task_versions` preserves existing IDs, state, assignment, due dates and audit history. It initializes existing tasks to version 1 and empty description, with `updated_at` set to their creation timestamp because earlier edit timestamps were not stored on tasks. Earlier edits remain available in the audit history. Apply the normal release migration before production startup and refresh clients before editing tasks.

Version 0.6.0 adds `0008_task_priorities`, backfilling normal priority without changing existing task versions, timestamps or audit events. `0009_user_language` adds the account interface preference. Apply both before starting the new server.
