"use client";
import { uiText } from "@/lib/i18n";

import { useState } from "react";
import { api, uiLabel as label, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Matter, User } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading, Modal } from "./ui";

type Member = {
  id: string;
  user_id: string;
  name: string;
  email: string;
  role: string;
};
const roles = [
  "matter_lead",
  "attorney",
  "review_manager",
  "reviewer",
  "expert",
  "read_only",
  "auditor",
];

export function MatterTeam({ matter, user }: { matter: Matter; user: User }) {
  const members = useResource<{ items: Member[] }>(
    `/cases/${matter.id}/members`,
  );
  const [add, setAdd] = useState(false),
    [remove, setRemove] = useState<Member | null>(null);
  const manage = can(matter.role, "manage");
  return (
    <section className="panel team-panel">
      <div className="section-heading">
        <div>
          <h2>{uiText("Matter team")}</h2>
          <p className="muted">
            {uiText(
              "Explicit matter access. Firm administration does not grant evidence access.",
            )}
          </p>
        </div>
        <button
          className="button secondary compact"
          onClick={() => setAdd(true)}
          disabled={!manage}
        >
          <Icon name="plus" size={15} />
          {uiText("Grant matter access")}
        </button>
      </div>
      <ErrorBox error={members.error} retry={members.refresh} />
      {members.loading && !members.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{uiText("Team member")}</th>
                <th>{uiText("Matter role")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {members.data?.items.map((member) => (
                <tr key={member.id}>
                  <td>
                    <strong>
                      {member.name}
                      {member.user_id === user.id && (
                        <small> {" " + uiText("· You")}</small>
                      )}
                    </strong>
                    <small className="block">{member.email}</small>
                  </td>
                  <td>
                    <Badge value={member.role} />
                  </td>
                  <td>
                    <button
                      className="button ghost compact danger-link"
                      disabled={!manage}
                      onClick={() => setRemove(member)}
                    >
                      {uiText("Remove access")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {add && (
        <AddMember
          matter={matter}
          user={user}
          close={() => setAdd(false)}
          done={() => {
            setAdd(false);
            members.refresh();
          }}
        />
      )}
      {remove && (
        <Modal
          title={uiText("Remove matter access")}
          close={() => setRemove(null)}
        >
          <RemoveMember
            matter={matter}
            member={remove}
            done={() => {
              setRemove(null);
              members.refresh();
            }}
          />
        </Modal>
      )}
    </section>
  );
}

function AddMember({
  matter,
  user,
  close,
  done,
}: {
  matter: Matter;
  user: User;
  close: () => void;
  done: () => void;
}) {
  const users = useResource<{ items: User[] }>(
    user.role === "firm_admin" ? "/users" : null,
  );
  const [newAccount, setNewAccount] = useState(false),
    [created, setCreated] = useState<User | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      let userId = data.get("user_id");
      if (newAccount) {
        const account =
          created ||
          (await post<User>("/users", {
            name: data.get("name"),
            email: data.get("email"),
            password: data.get("password"),
            role: "reviewer",
          }));
        setCreated(account);
        userId = account.id;
      }
      await post(`/cases/${matter.id}/members`, {
        user_id: userId,
        role: data.get("role"),
      });
      done();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={uiText("Grant matter access")} close={close}>
      <form onSubmit={submit}>
        <p className="muted">
          {uiText(
            "Grant access only to the intended person. The server checks account tenancy and records the role grant.",
          )}
        </p>
        <ErrorBox error={error} />
        {created && (
          <div className="notice amber">
            <Icon name="people" size={17} />
            <span>
              {uiText(
                "Local account created for {0}. Retry to finish granting access to this matter.",
                { "0": created.email },
              )}
            </span>
          </div>
        )}
        {user.role === "firm_admin" && !created && (
          <div className="account-mode">
            <button
              type="button"
              className={`button secondary compact ${!newAccount ? "chosen" : ""}`}
              onClick={() => setNewAccount(false)}
            >
              {uiText("Existing account")}
            </button>
            <button
              type="button"
              className={`button secondary compact ${newAccount ? "chosen" : ""}`}
              onClick={() => setNewAccount(true)}
            >
              {uiText("Create local account")}
            </button>
          </div>
        )}
        {newAccount ? (
          <>
            {!created && (
              <>
                <label>
                  {uiText("Name")}
                  <input
                    name="name"
                    required
                    maxLength={200}
                    autoComplete="off"
                  />
                </label>
                <label>
                  {uiText("Email")}
                  <input
                    name="email"
                    type="email"
                    required
                    maxLength={320}
                    autoComplete="off"
                  />
                </label>
                <label>
                  {uiText("Initial password")}
                  <input
                    name="password"
                    type="password"
                    required
                    minLength={12}
                    maxLength={1024}
                    autoComplete="new-password"
                  />
                </label>
              </>
            )}
            <div className="notice subtle">
              <Icon name="lock" size={17} />
              <span>
                {uiText(
                  "This creates a local account. Share its initial credentials through your firm's approved channel. No invitation email is sent.",
                )}
              </span>
            </div>
          </>
        ) : users.data ? (
          <label>
            {uiText("Existing firm account")}
            <select name="user_id" required>
              <option value="">{uiText("Select an account")}</option>
              {users.data.items.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name} · {account.email}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            {uiText("Existing account ID")}
            <input
              name="user_id"
              required
              placeholder={uiText(
                "Account ID supplied by your firm administrator",
              )}
            />
          </label>
        )}
        <label>
          {uiText("Matter access role")}
          <select name="role" defaultValue="reviewer">
            {roles.map((role) => (
              <option key={role} value={role}>
                {label(role)}
              </option>
            ))}
          </select>
        </label>
        <div className="form-actions">
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={close}
          >
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Granting access…") : uiText("Grant matter access")}
            <Icon name="arrow" size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}

function RemoveMember({
  matter,
  member,
  done,
}: {
  matter: Matter;
  member: Member;
  done: () => void;
}) {
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        setBusy(true);
        setError(null);
        try {
          await api(`/cases/${matter.id}/members/${member.user_id}`, {
            method: "DELETE",
            body: JSON.stringify({ reason: data.get("reason") }),
          });
          done();
        } catch (error) {
          setError(error);
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="muted">
        {uiText("Remove access for") + " "}
        <strong>{member.name}</strong> ({member.email}
        {uiText(
          ") to this matter. Their other authorized matters are unaffected.",
        )}
      </p>
      <ErrorBox error={error} />
      <label>
        {uiText("Reason")}
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
          {uiText(
            "I am authorized to remove this person's access to the matter.",
          )}
        </span>
      </label>
      <div className="form-actions">
        <button className="button primary" disabled={busy}>
          {busy
            ? uiText("Removing access…")
            : uiText("Remove authorized access")}
        </button>
      </div>
    </form>
  );
}
