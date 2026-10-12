"use client";

import { useState } from "react";
import { api, date, label, number, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { AuditEvent, User } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";

const roles = [
  "firm_admin",
  "attorney",
  "review_manager",
  "reviewer",
  "expert",
  "read_only",
  "auditor",
];

export default function FirmAdministration({ user }: { user: User }) {
  const users = useResource<{ items: User[] }>(
    user.role === "firm_admin" ? "/users" : null,
  );
  const [edit, setEdit] = useState<User | "new" | null>(null),
    [message, setMessage] = useState("");
  if (user.role !== "firm_admin")
    return (
      <Empty
        icon="lock"
        title="Administrator access required"
        text="Firm account administration is available only to firm administrators. Matter access remains separately controlled."
      />
    );
  return (
    <>
      <PageHeading
        eyebrow="FIRM ADMINISTRATION"
        title="Keep access deliberate."
        text="Manage local accounts and inspect system activity. Firm role changes affect account administration; existing matter roles are managed separately within each matter."
      >
        <button className="button primary" onClick={() => setEdit("new")}>
          <Icon name="plus" size={17} />
          Create local account
        </button>
      </PageHeading>
      {message && (
        <div className="notice green" role="status">
          <Icon name="check" size={17} />
          {message}
        </div>
      )}
      <ErrorBox error={users.error} retry={users.refresh} />
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>Firm accounts</h2>
            <p className="muted">
              Up to 200 accounts. Deactivation and role changes revoke the
              affected account’s sessions.
            </p>
          </div>
          <button className="button secondary compact" onClick={users.refresh}>
            Refresh accounts
          </button>
        </div>
        {users.loading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Firm role</th>
                  <th>Access</th>
                  <th>Authenticator</th>
                  <th>
                    <span className="sr-only">Account action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.data?.items.map((account) => (
                  <tr key={account.id}>
                    <td>
                      <strong>
                        {account.name}
                        {account.id === user.id ? " · You" : ""}
                      </strong>
                      <small className="block">{account.email}</small>
                    </td>
                    <td>
                      <Badge value={account.role} />
                    </td>
                    <td>
                      <Badge
                        value={account.active ? "Active" : "Deactivated"}
                        tone={account.active ? "green" : "red"}
                      />
                    </td>
                    <td>{account.mfa_enabled ? "Enabled" : "Not enabled"}</td>
                    <td>
                      <button
                        className="button secondary compact"
                        onClick={() => setEdit(account)}
                        disabled={account.id === user.id}
                      >
                        Edit account
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="field-help">
          Deactivation blocks access across all matters. A firm role change
          preserves existing matter memberships and their roles. Ask another
          administrator to change your own role or account status. At least one
          active firm administrator must remain.
        </p>
      </section>
      <SystemAudit />
      {edit && (
        <AccountModal
          account={edit === "new" ? null : edit}
          close={() => setEdit(null)}
          done={(revoked) => {
            setEdit(null);
            users.refresh();
            setMessage(
              revoked === null
                ? "Local account created. Grant matter access separately and share credentials through your authorized secure channel."
                : `Account updated. ${number(revoked)} sessions revoked.`,
            );
          }}
        />
      )}
    </>
  );
}

function AccountModal({
  account,
  close,
  done,
}: {
  account: User | null;
  close: () => void;
  done: (revoked: number | null) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal
      title={account ? `Edit ${account.name}` : "Create a local account"}
      close={close}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            if (account) {
              const result = await api<{ sessions_revoked: number }>(
                `/users/${account.id}`,
                {
                  method: "PATCH",
                  body: JSON.stringify({
                    role: form.get("role"),
                    active: form.get("active") === "true",
                    expected_active: account.active,
                    expected_role: account.role,
                    reason: form.get("reason"),
                  }),
                },
              );
              done(result.sessions_revoked);
            } else {
              await post("/users", {
                name: form.get("name"),
                email: form.get("email"),
                password: form.get("password"),
                role: form.get("role"),
              });
              done(null);
            }
          } catch (error) {
            setError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        {account ? (
          <>
            <p className="muted">{account.email}</p>
            <label>
              Account access
              <select name="active" defaultValue={String(account.active)}>
                <option value="true">Active</option>
                <option value="false">Deactivated</option>
              </select>
            </label>
          </>
        ) : (
          <>
            <label>
              Name
              <input name="name" required maxLength={200} autoComplete="off" />
            </label>
            <label>
              Email
              <input
                name="email"
                type="email"
                required
                maxLength={320}
                autoComplete="off"
              />
            </label>
            <label>
              Initial password
              <input
                name="password"
                type="password"
                required
                minLength={12}
                maxLength={1024}
                autoComplete="new-password"
              />
            </label>
            <p className="field-help">
              This creates a local account. No invitation email is sent.
            </p>
          </>
        )}
        <label>
          Firm role
          <select name="role" defaultValue={account?.role || "reviewer"}>
            {roles.map((role) => (
              <option key={role} value={role}>
                {label(role)}
              </option>
            ))}
          </select>
        </label>
        {account && (
          <>
            <label>
              Reason for change
              <textarea
                name="reason"
                required
                minLength={3}
                maxLength={2000}
                rows={3}
              />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" required />
              <span>
                I confirm this account access change and any resulting session
                revocation.
              </span>
            </label>
          </>
        )}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            Cancel
          </button>
          <button className="button primary" disabled={busy}>
            {busy
              ? "Saving…"
              : account
                ? "Save account change"
                : "Create account"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function SystemAudit() {
  const [cursor, setCursor] = useState<number | null>(null),
    [history, setHistory] = useState<(number | null)[]>([]);
  const audit = useResource<{
    items: AuditEvent[];
    before_sequence: number | null;
  }>(`/system/audit${cursor ? `?before_sequence=${cursor}` : ""}`);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [verification, setVerification] = useState<{
      valid: boolean;
      events_checked: number;
    } | null>(null);
  return (
    <section className="section">
      <div className="section-heading">
        <div>
          <h2>System audit trail</h2>
          <p className="muted">
            Account and system actions in your firm. Matter evidence actions
            stay in their own matter audit trail.
          </p>
        </div>
        <button
          className="button secondary compact"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              setVerification(await post("/system/audit/verify"));
            } catch (error) {
              setError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Icon name="shield" size={16} />
          {busy ? "Verifying…" : "Verify system chain"}
        </button>
      </div>
      <ErrorBox error={error || audit.error} retry={audit.refresh} />
      {verification && (
        <div
          className={`notice ${verification.valid ? "green" : "red"}`}
          role="status"
        >
          {verification.valid
            ? `System chain verified across ${number(verification.events_checked)} events.`
            : "System chain verification failed. Investigate before relying on this record."}
        </div>
      )}
      {audit.loading ? (
        <Loading />
      ) : (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date · UTC</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Target</th>
              </tr>
            </thead>
            <tbody>
              {audit.data?.items.map((event) => (
                <tr key={event.id}>
                  <td>{date(event.timestamp || event.created_at, true)}</td>
                  <td>
                    <strong>{label(event.event_type)}</strong>
                    <details className="audit-metadata">
                      <summary>Action details</summary>
                      <pre>
                        {JSON.stringify(
                          event.metadata || event.safe_metadata || {},
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </td>
                  <td className="mono">{event.actor_id || "System"}</td>
                  <td className="mono">{event.target_id || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!audit.data?.items.length && (
            <Empty
              icon="shield"
              title="No system events"
              text="Authorized account and security changes will be recorded here."
            />
          )}
        </div>
      )}
      <Pagination
        previous={
          history.length
            ? () => {
                const previous = [...history];
                setCursor(previous.pop() ?? null);
                setHistory(previous);
              }
            : undefined
        }
        next={
          audit.data?.before_sequence
            ? () => {
                setHistory([...history, cursor]);
                setCursor(audit.data!.before_sequence);
              }
            : undefined
        }
      />
      <p className="field-help">
        Hash chaining checks integrity within this deployment. It is not an
        independently protected, tamper-proof guarantee.
      </p>
    </section>
  );
}
