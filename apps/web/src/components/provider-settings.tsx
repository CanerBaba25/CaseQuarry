"use client";
import { uiText, type InterfaceMessage, type MessageKey } from "@/lib/i18n";

import { useEffect, useRef, useState } from "react";
import { api, date, getDisplayTimeZone } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading, Modal } from "./ui";

export const providers = [
  {
    id: "openai",
    name: "OpenAI API",
    description: "Models available through your OpenAI API account.",
  },
  {
    id: "gemini",
    name: "Google Gemini",
    description: "Models available through the Gemini API.",
  },
  {
    id: "xai",
    name: "Grok",
    description: "Models available through the xAI API.",
  },
  {
    id: "anthropic",
    name: "Claude",
    description: "Models available through the Anthropic API.",
  },
  {
    id: "kimi",
    name: "Kimi API (Moonshot)",
    description: "Models available through the Moonshot API.",
  },
] as const;
export function providerName(id: string) {
  if (id === "none") return uiText("Not configured");
  return id === "local"
    ? uiText("Local Ollama")
    : providers.find((provider) => provider.id === id)?.name || id;
}
type Credential = {
  provider: string;
  configured: boolean;
  masked_key: string | null;
  model: string | null;
  revision: number;
  revoked: boolean;
  updated_at: string | null;
};
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
export type CloudPolicy = {
  enabled: boolean;
  effective_enabled: boolean;
  server_capable: boolean;
  allowed_providers: string[];
  revision: number;
  warnings: string[];
};

export default function ProviderSettings({ user }: { user: User }) {
  const credentials = useResource<{ items: Credential[] }>("/ai/credentials");
  const policy = useResource<CloudPolicy>("/ai/cloud-policy");
  const [edit, setEdit] = useState<Credential | null>(null);
  const [remove, setRemove] = useState<Credential | null>(null);
  const [firmPolicy, setFirmPolicy] = useState<CloudPolicy | null>(null);
  const [message, setMessage] = useState<InterfaceMessage>("");
  function updated(text: MessageKey) {
    setEdit(null);
    setRemove(null);
    setMessage(text);
    credentials.refresh();
  }
  return (
    <section className="panel provider-settings">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{uiText("OPTIONAL SOURCE ASSISTANT")}</span>
          <h2>{uiText("Your provider connections")}</h2>
        </div>
        <Icon name="lock" />
      </div>
      <p className="muted">
        {uiText(
          "Add your own API key and model ID if you want to use an external provider. Keys are encrypted on the firm server and belong to your account. Saving a connection sends no vendor request.",
        )}
      </p>
      <p className="field-help">
        {uiText(
          "API access and usage charges are separate from ChatGPT, Gemini, Grok or Claude chat subscriptions. Firm approval, matter consent and confirmation for each job are required before selected source excerpts leave the firm server.",
        )}
      </p>
      {message && (
        <div className="notice green" role="status">
          {uiText(message)}
        </div>
      )}
      <ErrorBox error={credentials.error} retry={credentials.refresh} />
      {credentials.loading && !credentials.data ? (
        <Loading />
      ) : (
        <div className="provider-grid">
          {providers.map((provider) => {
            const credential = credentials.data?.items.find(
              (row) => row.provider === provider.id,
            );
            return (
              <article className="provider-card" key={provider.id}>
                <div className="section-heading">
                  <h3>{provider.name}</h3>
                  <Badge
                    value={
                      credential?.configured
                        ? "Saved · not tested"
                        : "Not connected"
                    }
                    tone={credential?.configured ? "green" : "neutral"}
                  />
                </div>
                <p className="muted">{uiText(provider.description)}</p>
                <dl className="metadata-list">
                  <div>
                    <dt>{uiText("Model ID")}</dt>
                    <dd className="mono">
                      {credential?.model || uiText("Choose when connecting")}
                    </dd>
                  </div>
                  <div>
                    <dt>{uiText("API key")}</dt>
                    <dd className="mono">
                      {credential?.masked_key || uiText("None saved")}
                    </dd>
                  </div>
                  {credential?.updated_at && (
                    <div>
                      <dt>
                        {uiText("Updated")} · {getDisplayTimeZone()}
                      </dt>
                      <dd>{date(credential.updated_at, true)}</dd>
                    </div>
                  )}
                </dl>
                <div className="button-row">
                  <button
                    className="button secondary compact"
                    disabled={!credential || credentials.loading}
                    onClick={() => {
                      setMessage("");
                      setEdit(credential!);
                    }}
                  >
                    {credential?.configured
                      ? uiText("Edit connection")
                      : uiText("Add API key")}
                  </button>
                  {credential?.configured && (
                    <button
                      className="button ghost compact danger-link"
                      onClick={() => setRemove(credential)}
                    >
                      {uiText("Remove key")}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      <div className="provider-firm-policy">
        <div className="section-heading">
          <div>
            <h3>{uiText("Firm external processing policy")}</h3>
            <p className="muted">
              {policy.data?.effective_enabled
                ? uiText("Permitted providers: {0}", {
                    "0": policy.data.allowed_providers
                      .map(providerName)
                      .join(", "),
                  })
                : uiText("External processing is disabled for the firm.")}
            </p>
          </div>
          {user.role === "firm_admin" && (
            <button
              className="button secondary compact"
              disabled={!policy.data || policy.loading}
              onClick={() => setFirmPolicy(policy.data!)}
            >
              {uiText("Manage firm policy")}
            </button>
          )}
        </div>
        <ErrorBox error={policy.error} retry={policy.refresh} />
        {policy.data?.server_capable === false && (
          <p className="field-help">
            {uiText(
              "The server administrator has disabled external providers on this installation.",
            )}
          </p>
        )}
      </div>
      {edit && (
        <CredentialEditor
          credential={edit}
          close={() => setEdit(null)}
          done={() =>
            updated(
              "Connection saved. No evidence was sent and the key has not been tested with the provider.",
            )
          }
        />
      )}
      {remove && (
        <RemoveCredential
          credential={remove}
          close={() => setRemove(null)}
          done={() =>
            updated(
              "Provider key removed. New requests using this connection are blocked.",
            )
          }
        />
      )}
      {firmPolicy && (
        <FirmPolicyEditor
          policy={firmPolicy}
          close={() => setFirmPolicy(null)}
          done={() => {
            setFirmPolicy(null);
            policy.refresh();
          }}
        />
      )}
    </section>
  );
}

function CredentialEditor({
  credential,
  close,
  done,
}: {
  credential: Credential;
  close: () => void;
  done: () => void;
}) {
  const live = useDialogLifetime();
  const [key, setKey] = useState("");
  const [model, setModel] = useState(credential.model || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal
      title={uiText("{0} connection", {
        "0": providerName(credential.provider),
      })}
      close={close}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api(`/ai/credentials/${credential.provider}`, {
              method: "PUT",
              body: JSON.stringify({
                model: model.trim(),
                expected_revision: credential.revision,
                ...(key ? { api_key: key } : {}),
              }),
            });
            if (live.current) {
              setKey("");
              done();
            }
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <p className="muted">
          {uiText(
            "Use a provider API key with access to the model you enter. Your key is never returned by the server after saving.",
          )}
        </p>
        <label>
          {uiText("API key")}{" "}
          {credential.configured && (
            <span className="optional">
              {uiText("leave blank to keep your current key")}
            </span>
          )}
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(event) => setKey(event.target.value)}
            required={!credential.configured}
            minLength={10}
            maxLength={512}
            disabled={busy}
          />
        </label>
        <label>
          {uiText("Model ID")}
          <input
            value={model}
            onChange={(event) => setModel(event.target.value)}
            required
            maxLength={200}
            spellCheck={false}
            autoComplete="off"
            disabled={busy}
          />
        </label>
        <p className="field-help">
          {uiText(
            "Copy the exact model ID from your provider account. Saving does not check the key or incur a model request.",
          )}
        </p>
        <div className="form-actions">
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Saving…") : uiText("Save connection")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
function RemoveCredential({
  credential,
  close,
  done,
}: {
  credential: Credential;
  close: () => void;
  done: () => void;
}) {
  const live = useDialogLifetime();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal
      title={uiText("Remove {0} key", {
        "0": providerName(credential.provider),
      })}
      close={close}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await api(`/ai/credentials/${credential.provider}`, {
              method: "DELETE",
              body: JSON.stringify({ reason: form.get("reason") }),
            });
            if (live.current) done();
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <p className="muted">
          {uiText(
            "This removes the encrypted key from your account and blocks queued requests that have not been transmitted.",
          )}
        </p>
        <label>
          {uiText("Reason")}
          <textarea
            name="reason"
            minLength={3}
            maxLength={2000}
            required
            rows={3}
            disabled={busy}
          />
        </label>
        <div className="form-actions">
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Removing…") : uiText("Remove key")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
function FirmPolicyEditor({
  policy,
  close,
  done,
}: {
  policy: CloudPolicy;
  close: () => void;
  done: () => void;
}) {
  const live = useDialogLifetime();
  const [enabled, setEnabled] = useState(policy.enabled);
  const [allowed, setAllowed] = useState(policy.allowed_providers);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal title={uiText("Firm external processing policy")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await api("/ai/cloud-policy", {
              method: "PATCH",
              body: JSON.stringify({
                enabled,
                allowed_providers: allowed,
                confirmed: form.get("confirmed") === "on",
                reason: form.get("reason"),
                expected_revision: policy.revision,
              }),
            });
            if (live.current) done();
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <p className="muted">
          {uiText(
            "Permitted providers can receive selected evidence excerpts only after matter approval and a separate confirmation for each job. Provider billing and retention terms apply.",
          )}
        </p>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy || !policy.server_capable}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span>{uiText("Allow external providers for this firm")}</span>
        </label>
        {providers.map((provider) => (
          <label className="checkbox-label" key={provider.id}>
            <input
              type="checkbox"
              checked={allowed.includes(provider.id)}
              disabled={busy || !enabled}
              onChange={(event) =>
                setAllowed((current) =>
                  event.target.checked
                    ? [...current, provider.id]
                    : current.filter((id) => id !== provider.id),
                )
              }
            />
            <span>{provider.name}</span>
          </label>
        ))}
        <label>
          {uiText("Reason")}
          <textarea
            name="reason"
            minLength={3}
            maxLength={2000}
            required
            rows={3}
            disabled={busy}
          />
        </label>
        <label className="checkbox-label">
          <input
            name="confirmed"
            type="checkbox"
            required={enabled}
            disabled={busy}
          />
          <span>
            {uiText(
              "I approve external processing by the selected providers under the firm’s data handling policy.",
            )}
          </span>
        </label>
        <div className="form-actions">
          <button
            className="button primary"
            disabled={busy || (enabled && !allowed.length)}
          >
            {busy ? uiText("Recording policy…") : uiText("Save firm policy")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
