"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading } from "./matter-pages";

export default function AccountSecurity({ user }: { user: User }) {
  const status = useResource<{ enabled: boolean; method: string }>(
    "/auth/mfa/status",
  );
  const [modal, setModal] = useState<"enroll" | "disable" | null>(null);
  return (
    <>
      <PageHeading
        eyebrow="YOUR ACCOUNT"
        title="Protect the way in."
        text="An authenticator adds a second step to signing in to your private workspace."
      />
      <div className="account-security-grid">
        <section className="panel security-profile">
          <span className="avatar light">
            {user.name.slice(0, 2).toUpperCase()}
          </span>
          <h2>{user.name}</h2>
          <p>{user.email}</p>
          <dl className="metadata-list">
            <div>
              <dt>Firm role</dt>
              <dd>{user.role.replace(/_/g, " ")}</dd>
            </div>
            <div>
              <dt>Matter access</dt>
              <dd>Granted separately per matter</dd>
            </div>
            <div>
              <dt>Sign-in</dt>
              <dd>Local account</dd>
            </div>
          </dl>
        </section>
        <section className="panel security-control">
          <div className="panel-heading">
            <Icon name="shield" size={25} />
            <div>
              <h2>Authenticator protection</h2>
              <p>Time-based one-time codes from your authenticator app.</p>
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
                    ? "Your account requires an authenticator code."
                    : "Add another layer to your sign-in."}
                </h3>
                <p>
                  {status.data.enabled
                    ? "Your password and a current six-digit code are required at sign-in. Enabling or disabling protection revokes your other active sessions."
                    : "Use an authenticator app that supports TOTP. The setup key is shown only when you explicitly start enrollment."}
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
                    ? "Disable authenticator"
                    : "Set up authenticator"}
                </button>
              </>
            )
          )}
        </section>
      </div>
      {modal && (
        <AuthenticatorModal
          kind={modal}
          close={() => setModal(null)}
          done={() => {
            setModal(null);
            status.refresh();
          }}
        />
      )}
    </>
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
        done();
      } else if (enrollment) {
        await post("/auth/mfa/confirm", { code: data.get("code") });
        done();
      } else {
        setEnrollment(
          await post("/auth/mfa/enroll", { password: data.get("password") }),
        );
      }
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        kind === "disable"
          ? "Disable authenticator protection"
          : "Set up your authenticator"
      }
      close={close}
    >
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        {enrollment ? (
          <>
            <p className="muted">
              Add a TOTP account in your authenticator using this setup key.
              Enter its current code to finish within{" "}
              {Math.floor(enrollment.expires_in / 60)} minutes.
            </p>
            <div className="authenticator-secret">
              <span className="eyebrow">PRIVATE SETUP KEY</span>
              <code>{enrollment.secret}</code>
              <button
                type="button"
                className="text-link"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(enrollment.secret);
                    setCopied(true);
                  } catch {
                    setCopied(false);
                  }
                }}
              >
                <Icon name="copy" size={14} />
                {copied ? "Copied setup key" : "Copy setup key"}
              </button>
            </div>
            <label>
              Current authenticator code
              <input
                name="code"
                required
                pattern="[0-9]{6}"
                maxLength={6}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="6 digits"
              />
            </label>
            <div className="notice subtle">
              <Icon name="lock" size={17} />
              <span>
                Keep this key private. It is not saved in browser storage. Other
                active sessions are revoked when protection is enabled.
              </span>
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              {kind === "disable"
                ? "Confirm with your password and current authenticator code. Your other active sessions will be revoked."
                : "Confirm your password to begin. Your authenticator setup key will then be shown for this enrollment."}
            </p>
            <label>
              Current password
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
              />
            </label>
            {kind === "disable" && (
              <label>
                Current authenticator code
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
            Cancel
          </button>
          <button className="button primary" disabled={busy}>
            {busy
              ? "Checking…"
              : kind === "disable"
                ? "Disable protection"
                : enrollment
                  ? "Enable authenticator"
                  : "Begin enrollment"}
            <Icon name="arrow" size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}
