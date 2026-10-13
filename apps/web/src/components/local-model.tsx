"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, date, label, number, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Matter, SearchSpec } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading } from "./matter-pages";
import { providers, providerName, type CloudPolicy } from "./provider-settings";

type Policy = {
  enabled: boolean;
  effective_enabled: boolean;
  configured: boolean;
  provider: string;
  endpoint: string | null;
  model: string | null;
  mode: string;
  warnings: string[];
  reason: string;
  revision: number;
  credential_revision?: number | null;
  firm_policy_revision?: number;
};
type Citation = {
  evidence_id: string;
  span_id: string;
  artifact_version: number;
  page: number | null;
  char_start: number;
  char_end: number;
  original_sha256: string;
  artifact_sha256: string;
  superseded?: boolean;
  current_artifact_version?: number;
};
type Finding = {
  id: string;
  claim: string;
  kind: string;
  source_citations: Citation[];
  human_review_status: string;
  confidence_label: string;
  superseded_sources?: boolean;
  source_acceptance_allowed?: boolean;
};
type Job = {
  id: string;
  job_id: string;
  state: string;
  model: string;
  model_tag?: string;
  model_version_status?: string;
  prompt_version: string;
  task: string;
  question: string;
  coverage: Record<string, number | boolean>;
  scope: unknown;
  answer: string | null;
  findings: Finding[];
  warnings: string[];
  error_code?: string | null;
  created_at: string;
  generated_at?: string;
  completed_at?: string;
};

export function LocalModelPolicy({ matter }: { matter: Matter }) {
  const resource = useResource<Policy>(`/cases/${matter.id}/ai/policy`);
  const firm = useResource<CloudPolicy>("/ai/cloud-policy");
  const [modal, setModal] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("local");
  const [expectedRevision, setExpectedRevision] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const data = resource.data;
  const external = provider !== "local";
  return (
    <section className="panel model-policy">
      <div className="section-heading">
        <h2>Source assistant policy</h2>
        <Icon name="lock" />
      </div>
      <ErrorBox error={resource.error} retry={resource.refresh} />
      <ErrorBox error={firm.error} retry={firm.refresh} />
      {resource.loading && !data ? (
        <Loading />
      ) : (
        data && (
          <>
            <Badge
              value={
                data.effective_enabled
                  ? "Enabled for your account"
                  : data.enabled
                    ? "Approval saved · unavailable"
                    : "Disabled for this matter"
              }
              tone={data.effective_enabled ? "green" : "neutral"}
            />
            <h3>
              {data.effective_enabled
                ? "Review exact source quotations."
                : "Your workflow works without a model."}
            </h3>
            <p>
              The optional adapter selects exact source quotations with verified
              citations. Each result requires human review before it can be
              accepted.
            </p>
            <dl className="metadata-list">
              <div>
                <dt>Provider</dt>
                <dd>{providerName(data.provider)}</dd>
              </div>
              <div>
                <dt>Your model</dt>
                <dd>{data.model || "Not configured"}</dd>
              </div>
              {data.endpoint && (
                <div>
                  <dt>
                    {providers.some((item) => item.id === data.provider)
                      ? "Provider endpoint"
                      : "Local endpoint"}
                  </dt>
                  <dd>{data.endpoint}</dd>
                </div>
              )}
              <div>
                <dt>External processing</dt>
                <dd>
                  {providers.some((item) => item.id === data.provider) &&
                  data.enabled
                    ? "Approved · each job needs confirmation"
                    : "Off for this matter"}
                </dd>
              </div>
              <div>
                <dt>Evidence scope</dt>
                <dd>This matter only</dd>
              </div>
            </dl>
            {data.warnings.map((warning, index) => (
              <p className="field-help" key={index}>
                {warning}
              </p>
            ))}
            {providers.some((item) => item.id === data.provider) &&
              !data.configured && (
                <Link className="text-link" href="/app/settings">
                  Add your provider API key in account settings
                  <Icon name="arrow" size={13} />
                </Link>
              )}
            {matter.role === "matter_lead" && (
              <button
                className="button secondary"
                disabled={busy || !firm.data}
                onClick={() => {
                  setEnabled(data.enabled);
                  setProvider(
                    providers.some((item) => item.id === data.provider)
                      ? data.provider
                      : "local",
                  );
                  setExpectedRevision(data.revision);
                  setError(null);
                  setModal(true);
                }}
              >
                Manage matter consent
              </button>
            )}
            {data.effective_enabled && (
              <Link
                className="button primary"
                href={`/app/matters/${matter.id}/ai`}
              >
                Open source assistant
                <Icon name="arrow" size={16} />
              </Link>
            )}
          </>
        )
      )}
      {modal && (
        <Modal title="Matter processing consent" close={() => setModal(false)}>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              setBusy(true);
              setError(null);
              try {
                await api(`/cases/${matter.id}/ai/policy`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    enabled,
                    provider,
                    data_sharing: external ? "on" : "off",
                    confirmed: form.get("confirmed") === "on",
                    reason: form.get("reason"),
                    expected_revision: expectedRevision,
                  }),
                });
                setModal(false);
                resource.refresh();
              } catch (error) {
                setError(error);
              } finally {
                setBusy(false);
              }
            }}
          >
            <ErrorBox error={error} />
            <label htmlFor="matter-provider">Provider</label>
            <select
              id="matter-provider"
              value={provider}
              disabled={busy}
              onChange={(event) => setProvider(event.target.value)}
            >
              <option value="local">Local Ollama</option>
              {providers.map((item) => (
                <option
                  key={item.id}
                  value={item.id}
                  disabled={
                    item.id !== data?.provider &&
                    !(
                      firm.data?.effective_enabled &&
                      firm.data.allowed_providers.includes(item.id)
                    )
                  }
                >
                  {item.name}
                  {!firm.data?.allowed_providers.includes(item.id)
                    ? " · firm approval required"
                    : ""}
                </option>
              ))}
            </select>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                disabled={busy}
              />
              <span>Enable the selected provider for this matter</span>
            </label>
            <p className="muted">
              {external
                ? "Selected evidence excerpts and the question are sent to this external provider when a user confirms a job. Each user must supply their own API key. Vendor billing and retention terms apply."
                : "Selected evidence is processed by the configured local runtime. The server administrator must disable Ollama Cloud and restrict runtime network access."}
            </p>
            <label>
              Purpose or reason
              <textarea
                name="reason"
                required
                minLength={3}
                maxLength={2000}
                rows={3}
                disabled={busy}
              />
            </label>
            <label className="checkbox-label">
              <input
                key={provider}
                name="confirmed"
                type="checkbox"
                required={enabled}
                disabled={busy}
              />
              <span>
                {external
                  ? "I approve sending selected source excerpts to this provider under the firm’s policy and this matter’s confidentiality requirements."
                  : "I verified the local runtime configuration, including OLLAMA_NO_CLOUD=1 and restricted network access."}
              </span>
            </label>
            <div className="form-actions">
              <button className="button primary" disabled={busy}>
                {busy ? "Recording consent…" : "Save matter consent"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export default function SourceAssistant({ matter }: { matter: Matter }) {
  const policy = useResource<Policy>(`/cases/${matter.id}/ai/policy`),
    jobs = useResource<{ items: Job[] }>(`/cases/${matter.id}/ai/jobs`);
  const [jobId, setJobId] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [review, setReview] = useState<Finding | null>(null),
    [decision, setDecision] = useState("accept");
  const [externalConfirmed, setExternalConfirmed] = useState(false);
  const selected = useResource<Job>(
    jobId ? `/cases/${matter.id}/ai/jobs/${jobId}` : null,
  );
  const external = providers.some((item) => item.id === policy.data?.provider);
  const active =
    selected.data &&
    ["pending", "queued", "running", "processing"].includes(
      selected.data.state.toLowerCase(),
    );
  useEffect(() => {
    setJobId(null);
    setError(null);
  }, [matter.id]);
  useEffect(() => {
    setExternalConfirmed(false);
  }, [
    matter.id,
    policy.data?.provider,
    policy.data?.model,
    policy.data?.revision,
    policy.data?.credential_revision,
    policy.data?.firm_policy_revision,
  ]);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      selected.refresh();
      jobs.refresh();
    }, 1800);
    return () => clearInterval(timer);
  }, [active, selected.refresh, jobs.refresh]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setExternalConfirmed(false);
    const ids = String(form.get("evidence_ids") || "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);
    setBusy(true);
    setError(null);
    if (ids.length > 50) {
      setError(
        new Error("Select at most 50 evidence IDs for a quotation job."),
      );
      setBusy(false);
      return;
    }
    const query: SearchSpec = {
      query: String(form.get("query") || ""),
      mode: "keyword",
      filters: {},
      sort: [{ field: "evidence_id", order: "asc" }],
      group_by: null,
      page_size: 50,
      cursor: null,
    };
    try {
      const job = await post<Job>(`/cases/${matter.id}/ai/ask`, {
        question: form.get("question"),
        ...(ids.length ? { evidence_ids: ids } : { query_spec: query }),
        style: "brief",
        ...(external
          ? {
              confirmed_external: form.get("confirmed_external") === "on",
              reason: String(form.get("external_reason") || ""),
            }
          : {}),
      });
      setJobId(job.id || job.job_id);
      jobs.refresh();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="SOURCE ASSISTANT"
        title="Return to the words themselves."
        text="Optional selection of exact source quotations. Each result is tied to a verified evidence location and requires human review."
      />
      <ErrorBox error={policy.error} retry={policy.refresh} />
      <ErrorBox error={jobs.error} retry={jobs.refresh} />
      <div className="assistant-grid">
        <section className="panel assistant-request">
          <div className="section-heading">
            <h2>Request source quotations</h2>
            <Badge
              value={
                policy.data?.effective_enabled
                  ? providerName(policy.data.provider)
                  : "Unavailable"
              }
              tone={policy.data?.effective_enabled ? "green" : "neutral"}
            />
          </div>
          {policy.loading ? (
            <Loading />
          ) : (
            !policy.data?.effective_enabled && (
              <div className="notice subtle">
                <Icon name="lock" size={18} />
                <span>
                  {policy.data?.configured
                    ? "The selected provider needs current firm approval, matter consent and a configured connection."
                    : "No usable model connection is configured for your account. Keyword search, review and exports remain available."}
                  <Link
                    className="text-link"
                    href={`/app/matters/${matter.id}/settings`}
                  >
                    Model policy
                    <Icon name="arrow" size={13} />
                  </Link>
                </span>
              </div>
            )
          )}
          <form
            onSubmit={submit}
            onChange={(event) => {
              const target = event.target;
              if (
                (target instanceof HTMLInputElement ||
                  target instanceof HTMLTextAreaElement ||
                  target instanceof HTMLSelectElement) &&
                target.name !== "confirmed_external"
              )
                setExternalConfirmed(false);
            }}
          >
            <ErrorBox error={error} />
            <label>
              Question or extraction focus
              <textarea
                name="question"
                required
                minLength={3}
                maxLength={2000}
                rows={3}
                placeholder="Which source passages discuss payment approval?"
                disabled={!policy.data?.effective_enabled}
              />
            </label>
            <label>
              Evidence query <span className="optional">optional</span>
              <input
                name="query"
                maxLength={4096}
                placeholder={'e.g. "Project Atlas" AND approval'}
                disabled={!policy.data?.effective_enabled}
              />
            </label>
            <label>
              Specific evidence IDs <span className="optional">optional</span>
              <textarea
                name="evidence_ids"
                rows={2}
                placeholder="Up to 50 comma-separated evidence IDs"
                disabled={!policy.data?.effective_enabled}
              />
            </label>
            <p className="field-help">
              Specific IDs take precedence over the query. Retrieval is bounded
              to 50 items and 40 source spans; coverage is displayed with the
              result.
            </p>
            {external && (
              <div
                className="external-job-confirmation"
                key={`${policy.data?.provider}:${policy.data?.model}`}
              >
                <p className="field-help">
                  This request sends your question and selected source excerpts
                  to {providerName(policy.data!.provider)} using your saved
                  model ({policy.data!.model || "not configured"}). Provider
                  charges and retention terms apply.
                </p>
                <label>
                  External processing purpose
                  <textarea
                    name="external_reason"
                    required
                    minLength={3}
                    maxLength={2000}
                    rows={2}
                    disabled={busy || !policy.data?.effective_enabled}
                  />
                </label>
                <label className="checkbox-label">
                  <input
                    name="confirmed_external"
                    type="checkbox"
                    checked={externalConfirmed}
                    onChange={(event) =>
                      setExternalConfirmed(event.target.checked)
                    }
                    required
                    disabled={busy || !policy.data?.effective_enabled}
                  />
                  <span>
                    I approve sending this job’s selected excerpts to{" "}
                    {providerName(policy.data!.provider)}.
                  </span>
                </label>
              </div>
            )}
            <button
              className="button primary"
              disabled={busy || !policy.data?.effective_enabled}
            >
              {busy ? "Requesting job…" : "Extract source quotations"}
              <Icon name="arrow" size={17} />
            </button>
          </form>
        </section>
        <section className="panel assistant-history">
          <div className="section-heading">
            <h2>Recent jobs</h2>
            <button className="button ghost compact" onClick={jobs.refresh}>
              Refresh
            </button>
          </div>
          {jobs.loading && !jobs.data ? (
            <Loading />
          ) : !jobs.data?.items.length ? (
            <Empty
              icon="sparkle"
              title="No model jobs yet"
              text="Explicitly requested jobs appear here. Importing evidence never starts a model job automatically."
            />
          ) : (
            <div className="assistant-job-list">
              {jobs.data.items.map((job) => (
                <button
                  key={job.id}
                  className={jobId === job.id ? "selected" : ""}
                  onClick={() => setJobId(job.id)}
                >
                  <Icon name="file" size={17} />
                  <span>
                    <strong>
                      {job.question || "Source quotation request"}
                    </strong>
                    <small>{date(job.created_at, true)}</small>
                  </span>
                  <Badge value={job.state} />
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
      {jobId && (
        <section className="panel assistant-result">
          <ErrorBox error={selected.error} retry={selected.refresh} />
          {selected.loading && !selected.data ? (
            <Loading text="Opening source quotation job…" />
          ) : (
            selected.data && (
              <>
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">REVIEWED SCOPE</span>
                    <h2>{selected.data.question}</h2>
                  </div>
                  <Badge value={selected.data.state} />
                </div>
                <div className="assistant-coverage">
                  {[
                    "matched_items",
                    "selected_items",
                    "processed_items",
                    "failed_items",
                    "partial_items",
                    "restricted_items",
                    "omitted_items",
                    "retrieved_spans",
                  ].map((key) => (
                    <div key={key}>
                      <strong>
                        {typeof selected.data!.coverage?.[key] === "number"
                          ? number(selected.data!.coverage[key] as number)
                          : "—"}
                      </strong>
                      <span>{label(key)}</span>
                    </div>
                  ))}
                </div>
                {selected.data.coverage?.sampled && (
                  <div className="notice amber">
                    <Icon name="alert" size={17} />
                    This job covers a bounded subset of the matching record. It
                    is not an exhaustive matter review.
                  </div>
                )}
                {selected.data.error_code && (
                  <div className="notice red">
                    <Icon name="alert" size={17} />
                    <span>
                      Local quotation extraction failed:{" "}
                      {label(selected.data.error_code)}. Check the local runtime
                      before requesting another job.
                    </span>
                  </div>
                )}
                {selected.data.findings?.length ? (
                  <div className="quotation-list">
                    {selected.data.findings.map((finding) => (
                      <article key={finding.id} className="quotation-card">
                        <div>
                          <span className="eyebrow">
                            MODEL-SELECTED SOURCE QUOTATION
                          </span>
                          <Badge
                            value={`${finding.human_review_status}${finding.superseded_sources ? " · prior source version" : ""}`}
                            tone={
                              finding.superseded_sources
                                ? "amber"
                                : finding.human_review_status === "accepted"
                                  ? "green"
                                  : finding.human_review_status === "rejected"
                                    ? "red"
                                    : "amber"
                            }
                          />
                        </div>
                        <blockquote>{finding.claim}</blockquote>
                        {finding.superseded_sources && (
                          <div className="notice amber">
                            <Icon name="alert" size={16} />
                            <span>
                              This quotation uses a superseded extraction. Its
                              previous human review record is preserved. Rerun
                              against the current source before recording a new
                              acceptance.
                            </span>
                          </div>
                        )}
                        <div className="quotation-citations">
                          {finding.source_citations.map((citation, i) => (
                            <Link
                              key={`${citation.span_id}-${i}`}
                              href={`/app/matters/${matter.id}/evidence/${citation.evidence_id}?version=${citation.artifact_version}#span-${citation.span_id}`}
                            >
                              <Icon name="file" size={14} />
                              <span>
                                {citation.evidence_id.slice(0, 12)} ·{" "}
                                {citation.page
                                  ? `Page ${citation.page}`
                                  : `Chars ${citation.char_start}–${citation.char_end}`}{" "}
                                · v{citation.artifact_version}
                              </span>
                              <Icon name="arrow" size={14} />
                            </Link>
                          ))}
                        </div>
                        <div className="quotation-review">
                          <span>
                            Source context requires professional review.
                          </span>
                          <button
                            className="button secondary compact"
                            disabled={!can(matter.role, "review")}
                            onClick={() => {
                              setReview(finding);
                              setDecision(
                                finding.source_acceptance_allowed === false
                                  ? "reject"
                                  : "accept",
                              );
                            }}
                          >
                            Review quotation
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : ["completed", "ready"].includes(
                    selected.data.state.toLowerCase(),
                  ) ? (
                  <Empty
                    icon="search"
                    title="Insufficient evidence from the reviewed scope"
                    text="No supported source quotation was accepted by the citation validator. Try a narrower evidence scope or inspect the original sources."
                  />
                ) : active ? (
                  <Loading text="The local runtime is processing this bounded scope…" />
                ) : null}
                <details className="assistant-provenance">
                  <summary>Model and coverage details</summary>
                  <dl className="metadata-list">
                    <div>
                      <dt>Configured model tag</dt>
                      <dd>{selected.data.model_tag || selected.data.model}</dd>
                    </div>
                    <div>
                      <dt>Weights fingerprint</dt>
                      <dd>
                        {selected.data.model_version_status || "Not recorded"}
                      </dd>
                    </div>
                    <div>
                      <dt>Template version</dt>
                      <dd>{selected.data.prompt_version}</dd>
                    </div>
                    <div>
                      <dt>Generated</dt>
                      <dd>
                        {date(
                          selected.data.generated_at ||
                            selected.data.completed_at,
                          true,
                        )}
                      </dd>
                    </div>
                  </dl>
                  {selected.data.warnings?.map((warning, i) => (
                    <p className="field-help" key={i}>
                      {warning}
                    </p>
                  ))}
                </details>
              </>
            )
          )}
        </section>
      )}
      {review && (
        <Modal title="Review a source quotation" close={() => setReview(null)}>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              setBusy(true);
              setError(null);
              try {
                await post(
                  `/cases/${matter.id}/ai/findings/${review.id}/review`,
                  { decision, reason: form.get("reason") },
                );
                setReview(null);
                selected.refresh();
              } catch (error) {
                setError(error);
              } finally {
                setBusy(false);
              }
            }}
          >
            <p className="muted">
              This reviews the model-selected source quotation. Evidence review
              and privilege decisions remain recorded in the evidence inspector.
            </p>
            <ErrorBox error={error} />
            <label>
              Decision
              <select
                value={decision}
                onChange={(event) => setDecision(event.target.value)}
              >
                <option
                  value="accept"
                  disabled={review.source_acceptance_allowed === false}
                >
                  Accept quotation after source review
                </option>
                <option value="reject">Reject quotation</option>
              </select>
            </label>
            <label>
              Review reason
              <textarea
                name="reason"
                required
                minLength={3}
                maxLength={2000}
                rows={3}
              />
            </label>
            <div className="form-actions">
              <button
                className="button primary"
                disabled={
                  busy ||
                  (decision === "accept" &&
                    review.source_acceptance_allowed === false)
                }
              >
                {busy ? "Saving review…" : "Record quotation review"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
