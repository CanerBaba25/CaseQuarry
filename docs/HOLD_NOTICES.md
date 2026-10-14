# Custodian hold-notice register

Open a matter's **Preservation holds**, then choose **View notices** on a hold.
CaseQuarry 0.8.0 records staff-managed notices for that hold's custodians. It does
not send notices or reminders, authenticate a custodian's acknowledgement or judge
whether the wording or delivery satisfies a legal obligation.

## Record a notice

1. Add the custodian in **Sources & imports** if necessary.
2. Choose **Register notice**, select that matter's custodian and enter the exact
   notice text, an optional next reminder date and a reason. One notice is permitted
   per hold/custodian pair. New records start as drafts.
3. Save any text changes before choosing **Record issuance**. Record issuance only
   after completing the appropriate professional delivery process separately.
4. Issuance permanently freezes the notice text and its SHA-256. Reminder dates can
   still be changed while acknowledgement is outstanding. Planning a date alone
   does not record a reminder as having occurred.
5. **Record reminder** records a staff-reported reminder and can set the next date.
   **Record acknowledgement** captures the supplied name and the staff member/time
   recording it, then clears the reminder date. The name is a manual claim rather
   than verified custodian identity. Acknowledged notices are read-only.

Each change requires a reason and the version displayed when editing. A conflicting
save retains your draft; load and inspect the latest record before saving again.
The app does not silently retry an action against a newer version. Action history
records versions, actors, timestamps, reasons and the relevant changed metadata;
notice text is not duplicated into every audit event.

## Scope, dates and release

All current matter viewers can inspect the register. Only a current matter lead or
attorney with hold permission can change it. Both the hold and custodian must belong
to the same authorized tenant and matter. An active parent hold is required for
every notice mutation, including acknowledgement and reminders.

Counts cover the whole authorized hold register across pages. Awaiting
acknowledgement counts issued notices; drafts are separate. An issued notice is
overdue when its next reminder date is before today's calendar date in your saved
account timezone. A reminder due today is not yet overdue. Dates are entered as
calendar dates and do not shift when another user chooses a different timezone.

Releasing a preservation hold preserves the notices and their history and makes
the register read-only. The register never releases a hold, deletes originals,
changes disclosure eligibility or grants access to a matter. Create a new hold
for replacement wording after issuance; keep the prior history.

## API contract

All routes below are relative to `/api/v1/cases/{case_id}/holds/{hold_id}/notices`.
Cookie-authenticated mutations require the current CSRF token. JSON uses the
published request schema and rejects unknown fields and embedded NUL characters.

| Method and suffix               | Request and behavior                                                                                                                                                      |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /`                         | `limit` 1–200, optional scoped `cursor`; paged metadata, full-register `summary`, `hold_state`, `server_today` and `time_zone`. Notice text is omitted from listing rows. |
| `POST /`                        | `custodian_id`, `notice_text` (1–20,000 characters), `reason`, optional `next_reminder_date` (`YYYY-MM-DD` or null); creates a draft.                                     |
| `GET /{notice_id}`              | Exact text/hash, version, lifecycle actors/times, reminder fields and explicit `manual_recording: true`, `identity_verified: false`.                                      |
| `PATCH /{notice_id}`            | `expected_version`, `reason`, and `notice_text` and/or `next_reminder_date`; text is draft-only, acknowledged records reject edits. Explicit null clears a reminder date. |
| `POST /{notice_id}/issue`       | `expected_version`, `reason`; draft → issued.                                                                                                                             |
| `POST /{notice_id}/acknowledge` | `expected_version`, `reason`, `acknowledgement_name` (1–200 characters); issued → acknowledged.                                                                           |
| `POST /{notice_id}/remind`      | `expected_version`, `reason`, optional `next_reminder_date`; issued notices only, increments the manually recorded reminder count.                                        |
| `GET /{notice_id}/history`      | Paged newest-first events with `limit` and scoped `cursor`; remains available after hold release.                                                                         |

Version conflicts return HTTP 409 `HOLD_NOTICE_CONFLICT`; duplicate custodians
return `HOLD_NOTICE_EXISTS`. Released holds reject changes with `HOLD_INACTIVE`.
Invalid lifecycle transitions and frozen text have explicit conflict codes.
Malformed dates/text, missing versions and invalid paging inputs return validation
errors. Dates and summary counts are derived by the server; do not substitute a
client's UTC day for the reported account-local day.

The authenticated CLI's `cq api request` can call these routes using a private
bounded JSON `--body` file. Generic API access preserves the same permissions,
versions and manual-recording rules as the browser and desktop workspaces.
