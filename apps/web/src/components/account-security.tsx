"use client";
import { uiMessage, uiText, type InterfaceMessage } from "@/lib/i18n";

import { useEffect, useRef, useState } from "react";
import {
  csrfToken,
  date,
  getDisplayTimeZone,
  uiLabel as label,
  number,
  post,
} from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading } from "./matter-pages";
import ProviderSettings from "./provider-settings";

function useDialogLifetime() {
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  return live;
}

export default function AccountSecurity({
  user,
  preferences,
}: {
  user: User;
  preferences?: React.ReactNode;
}) {
  const status = useResource<{ enabled: boolean; method: string }>(
    "/auth/mfa/status",
  );
  const [modal, setModal] = useState<"enroll" | "disable" | null>(null);
  const [passwordModal, setPasswordModal] = useState(false);
  const sessions = useResource<{
    items: {
      id: string;
      current: boolean;
      created_at: string;
      expires_at: string;
    }[];
    limit: number;
  }>("/auth/sessions");
  const [revoke, setRevoke] = useState<{ id: string; current: boolean } | null>(
      null,
    ),
    [message, setMessage] = useState<InterfaceMessage>("");
  return (
    <>
      <PageHeading
        eyebrow={uiText("YOUR ACCOUNT")}
        title={uiText("Protect the way in.")}
        text={uiText(
          "An authenticator adds a second step to signing in to your private workspace.",
        )}
      />
      {preferences}
      <div className="account-security-grid">
        <section className="panel security-profile">
          <span className="avatar light">
            {user.name.slice(0, 2).toUpperCase()}
          </span>
          <h2>{user.name}</h2>
          <p>{user.email}</p>
          <dl className="metadata-list">
            <div>
              <dt>{uiText("Firm role")}</dt>
              <dd>{label(user.role)}</dd>
            </div>
            <div>
              <dt>{uiText("Matter access")}</dt>
              <dd>{uiText("Granted separately per matter")}</dd>
            </div>
            <div>
              <dt>{uiText("Timezone")}</dt>
              <dd>{user.time_zone || uiText("UTC")}</dd>
            </div>
            <div>
              <dt>{uiText("Sign-in")}</dt>
              <dd>{uiText("Local account")}</dd>
            </div>
          </dl>
        </section>
        <section className="panel security-control">
          <div className="panel-heading">
            <Icon name="shield" size={25} />
            <div>
              <h2>{uiText("Authenticator protection")}</h2>
              <p>
                {uiText(
                  "Time-based one-time codes from your authenticator app.",
                )}
              </p>
            </div>
          </div>
          <ErrorBox error={status.error} retry={status.refresh} />
          {status.loading ? (
            <Loading />
          ) : (
            status.data && (
              <>
                <Badge
                  value={status.data.enabled ? "Enabled" : "Not enabled"}
                  tone={status.data.enabled ? "green" : "amber"}
                />
                <h3>
                  {status.data.enabled
                    ? uiText("Your account requires an authenticator code.")
                    : uiText("Add another layer to your sign-in.")}
                </h3>
                <p>
                  {status.data.enabled
                    ? uiText(
                        "Your password and a current six-digit code are required at sign-in. Enabling or disabling protection revokes your other active sessions.",
                      )
                    : uiText(
                        "Use an authenticator app that supports TOTP. The setup key is shown only when you explicitly start enrollment.",
                      )}
                </p>
                <button
                  className={`button ${status.data.enabled ? "secondary" : "primary"}`}
                  onClick={() =>
                    setModal(status.data!.enabled ? "disable" : "enroll")
                  }
                >
                  <Icon
                    name={status.data.enabled ? "lock" : "plus"}
                    size={17}
                  />
                  {status.data.enabled
                    ? uiText("Disable authenticator")
                    : uiText("Set up authenticator")}
                </button>
              </>
            )
          )}
        </section>
      </div>
      <section className="panel security-password">
        <div className="section-heading">
          <div>
            <h2>{uiText("Password")}</h2>
            <p className="muted">
              {uiText(
                "Changing your password revokes your other sessions and preserves this one.",
              )}
            </p>
          </div>
          <button
            className="button secondary"
            onClick={() => setPasswordModal(true)}
            disabled={!status.data || status.loading}
          >
            {uiText("Change password")}
          </button>
        </div>
      </section>
      {message && (
        <div className="notice green" role="status">
          <Icon name="check" size={17} />
          {uiText(message)}
        </div>
      )}
      <section className="panel sessions-panel">
        <div className="section-heading">
          <div>
            <h2>{uiText("Active sign-ins")}</h2>
            <p className="muted">
              {uiText(
                "Up to 100 active sessions for your account. Times are shown in {0}.",
                { "0": getDisplayTimeZone(user.time_zone || "UTC") },
              )}
            </p>
          </div>
          <button
            className="button secondary compact"
            onClick={sessions.refresh}
          >
            {uiText("Refresh sessions")}
          </button>
        </div>
        <ErrorBox error={sessions.error} retry={sessions.refresh} />
        {sessions.loading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{uiText("Session")}</th>
                  <th>
                    {uiText("Signed in · {0}", {
                      "0": getDisplayTimeZone(user.time_zone || "UTC"),
                    })}
                  </th>
                  <th>
                    {uiText("Expires · {0}", {
                      "0": getDisplayTimeZone(user.time_zone || "UTC"),
                    })}
                  </th>
                  <th>
                    <span className="sr-only">{uiText("Session action")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sessions.data?.items.map((session) => (
                  <tr key={session.id}>
                    <td>
                      <Badge
                        value={
                          session.current ? "This session" : "Other session"
                        }
                        tone={session.current ? "green" : "neutral"}
                      />
                      <small className="block mono">{session.id}</small>
                    </td>
                    <td>{date(session.created_at, true)}</td>
                    <td>{date(session.expires_at, true)}</td>
                    <td>
                      <button
                        className="button ghost compact danger-link"
                        onClick={() => setRevoke(session)}
                      >
                        {session.current
                          ? uiText("Sign out here")
                          : uiText("Revoke session")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <ProviderSettings user={user} />
      {passwordModal && (
        <PasswordModal
          mfaEnabled={status.data?.enabled || false}
          close={() => setPasswordModal(false)}
          done={(count) => {
            setPasswordModal(false);
            setMessage(
              uiMessage("Password changed. {0} other sessions revoked.", {
                "0": number(count),
              }),
            );
            sessions.refresh();
          }}
        />
      )}
      {revoke && (
        <RevokeSession
          key={revoke.id}
          id={revoke.id}
          current={revoke.current}
          close={() => setRevoke(null)}
          done={(current) => {
            setRevoke(null);
            if (current) window.dispatchEvent(new Event("cq:unauthorized"));
            else {
              sessions.refresh();
              setMessage("The selected session was revoked.");
            }
          }}
        />
      )}
      {modal && (
        <AuthenticatorModal
          key={modal}
          kind={modal}
          close={() => setModal(null)}
          done={() => {
            setModal(null);
            status.refresh();
            sessions.refresh();
          }}
        />
      )}
    </>
  );
}

function PasswordModal({
  mfaEnabled,
  close,
  done,
}: {
  mfaEnabled: boolean;
  close: () => void;
  done: (count: number) => void;
}) {
  const live = useDialogLifetime();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal title={uiText("Change your password")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setError(null);
          if (data.get("new_password") !== data.get("confirmation")) {
            setError(
              new Error("The new password and confirmation must match."),
            );
            return;
          }
          setBusy(true);
          try {
            const result = await post<{ other_sessions_revoked: number }>(
              "/auth/password/change",
              {
                current_password: data.get("current_password"),
                new_password: data.get("new_password"),
                ...(data.get("totp_code")
                  ? { totp_code: data.get("totp_code") }
                  : {}),
              },
            );
            if (live.current) done(result.other_sessions_revoked);
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <label>
          {uiText("Current password")}
          <input
            name="current_password"
            type="password"
            required
            autoComplete="current-password"
            maxLength={1024}
          />
        </label>
        <label>
          {uiText("New password")}
          <input
            name="new_password"
            type="password"
            required
            minLength={12}
            maxLength={1024}
            autoComplete="new-password"
          />
        </label>
        <label>
          {uiText("Confirm new password")}
          <input
            name="confirmation"
            type="password"
            required
            minLength={12}
            maxLength={1024}
            autoComplete="new-password"
          />
        </label>
        {mfaEnabled && (
          <label>
            {uiText("Current authenticator code")}
            <input
              name="totp_code"
              required
              pattern="[0-9]{6}"
              maxLength={6}
              inputMode="numeric"
              autoComplete="one-time-code"
            />
          </label>
        )}
        <div className="notice amber">
          <Icon name="lock" size={17} />
          <span>
            {uiText(
              "Your other active sessions will be signed out after this change.",
            )}
          </span>
        </div>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Changing…") : uiText("Change password")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function RevokeSession({
  id,
  current,
  close,
  done,
}: {
  id: string;
  current: boolean;
  close: () => void;
  done: (current: boolean) => void;
}) {
  const live = useDialogLifetime();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal
      title={
        current
          ? uiText("Sign out this session")
          : uiText("Revoke the selected session")
      }
      close={close}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const submittedSession = csrfToken();
          setBusy(true);
          setError(null);
          try {
            const result = await post<{ current: boolean }>(
              `/auth/sessions/${id}/revoke`,
              { reason: data.get("reason") },
            );
            if (live.current) done(result.current);
            else if (result.current && csrfToken() === submittedSession)
              window.dispatchEvent(new Event("cq:unauthorized"));
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <p className="muted">
          {current
            ? uiText("This browser will return to the sign-in page.")
            : uiText(
                "The selected session will no longer have access. The account can sign in again with its credentials.",
              )}
        </p>
        <ErrorBox error={error} />
        <label>
          {uiText("Reason")}
          <input name="reason" required minLength={3} maxLength={2000} />
        </label>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy
              ? uiText("Revoking…")
              : current
                ? uiText("Sign out")
                : uiText("Revoke session")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AuthenticatorModal({
  kind,
  close,
  done,
}: {
  kind: "enroll" | "disable";
  close: () => void;
  done: () => void;
}) {
  const live = useDialogLifetime();
  const [enrollment, setEnrollment] = useState<{
      secret: string;
      provisioning_uri: string;
      expires_in: number;
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [copied, setCopied] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      if (kind === "disable") {
        await post("/auth/mfa/disable", {
          password: data.get("password"),
          code: data.get("code"),
        });
        if (live.current) done();
      } else if (enrollment) {
        await post("/auth/mfa/confirm", { code: data.get("code") });
        if (live.current) done();
      } else {
        const result = await post<NonNullable<typeof enrollment>>(
          "/auth/mfa/enroll",
          { password: data.get("password") },
        );
        if (live.current) setEnrollment(result);
      }
    } catch (error) {
      if (live.current) setError(error);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <Modal
      title={
        kind === "disable"
          ? uiText("Disable authenticator protection")
          : uiText("Set up your authenticator")
      }
      close={close}
    >
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        {enrollment ? (
          <>
            <p className="muted">
              {uiText(
                "Add a TOTP account in your authenticator using this setup key. Enter its current code to finish within {0} minutes.",
                { "0": Math.floor(enrollment.expires_in / 60) },
              )}
            </p>
            <div className="authenticator-secret">
              <span className="eyebrow">{uiText("PRIVATE SETUP KEY")}</span>
              <code>{enrollment.secret}</code>
              <button
                type="button"
                className="text-link"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(enrollment.secret);
                    if (live.current) setCopied(true);
                  } catch {
                    if (live.current) setCopied(false);
                  }
                }}
              >
                <Icon name="copy" size={14} />
                {copied ? uiText("Copied setup key") : uiText("Copy setup key")}
              </button>
            </div>
            <label>
              {uiText("Current authenticator code")}
              <input
                name="code"
                required
                pattern="[0-9]{6}"
                maxLength={6}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder={uiText("6 digits")}
              />
            </label>
            <div className="notice subtle">
              <Icon name="lock" size={17} />
              <span>
                {uiText(
                  "Keep this key private. It is not saved in browser storage. Other active sessions are revoked when protection is enabled.",
                )}
              </span>
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              {kind === "disable"
                ? uiText(
                    "Confirm with your password and current authenticator code. Your other active sessions will be revoked.",
                  )
                : uiText(
                    "Confirm your password to begin. Your authenticator setup key will then be shown for this enrollment.",
                  )}
            </p>
            <label>
              {uiText("Current password")}
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
              />
            </label>
            {kind === "disable" && (
              <label>
                {uiText("Current authenticator code")}
                <input
                  name="code"
                  required
                  pattern="[0-9]{6}"
                  maxLength={6}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />
              </label>
            )}
          </>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={busy}
          >
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy
              ? uiText("Checking…")
              : kind === "disable"
                ? uiText("Disable protection")
                : enrollment
                  ? uiText("Enable authenticator")
                  : uiText("Begin enrollment")}
            <Icon name="arrow" size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}
