"use client";
import ManifestSigningStatus from "./manifest-signing";
import { uiText } from "@/lib/i18n";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { bytes, csrfToken, uiLabel as label, number, post } from "@/lib/api";
import { useMountedRef, useResource } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { EvidenceDetail, Matter, User } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";
import PdfRegionSelector from "./pdf-region-selector";

type Range = { start: number; end: number };
type Region = {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
};
type Redaction = {
  id: string;
  evidence_id: string;
  kind: "pdf" | "text";
  state: string;
  requested_by: string;
  approved_by: string | null;
  reason: string;
  sha256: string | null;
  byte_size: number;
  verification: Record<string, unknown>;
  error: string | null;
  error_code: string | null;
  selection: { ranges?: Range[]; regions?: Region[] };
};
type Production = {
  id: string;
  state: string;
  requested_by: string;
  approved_by: string | null;
  reason: string;
  bates_prefix: string;
  evidence_ids: string[];
  redactions: Record<string, string>;
  counts: Record<string, unknown>;
  sha256: string | null;
  byte_size: number;
  error?: string;
  items?: {
    evidence_id: string;
    begin_bates: string;
    end_bates: string;
    page_count: number;
    produced_sha256: string;
  }[];
};

export default function ProductionsPage({
  matter,
  user,
}: {
  matter: Matter;
  user: User;
}) {
  const params = useSearchParams();
  const [redactionCursor, setRedactionCursor] = useState<string | null>(null),
    [redactionHistory, setRedactionHistory] = useState<(string | null)[]>([]),
    [productionCursor, setProductionCursor] = useState<string | null>(null),
    [productionHistory, setProductionHistory] = useState<(string | null)[]>([]);
  const redactions = useResource<{
    items: Redaction[];
    next_cursor: string | null;
  }>(
    can(matter.role, "review")
      ? `/cases/${matter.id}/redactions${redactionCursor ? `?cursor=${encodeURIComponent(redactionCursor)}` : ""}`
      : null,
  );
  const productions = useResource<{
    items: Production[];
    next_cursor: string | null;
  }>(
    can(matter.role, "export")
      ? `/cases/${matter.id}/productions${productionCursor ? `?cursor=${encodeURIComponent(productionCursor)}` : ""}`
      : null,
  );
  const [createRedaction, setCreateRedaction] = useState(false),
    [createProduction, setCreateProduction] = useState(false),
    [redactionId, setRedactionId] = useState<string | null>(null),
    [productionId, setProductionId] = useState<string | null>(null);
  useEffect(() => {
    if (params.get("evidence_id") && can(matter.role, "review"))
      setCreateRedaction(true);
  }, [params, matter.role]);
  const pending =
    redactions.data?.items.some((item) =>
      ["pending", "running"].includes(item.state),
    ) ||
    productions.data?.items.some((item) =>
      ["pending", "running"].includes(item.state),
    );
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => {
      redactions.refresh();
      productions.refresh();
    }, 2500);
    return () => clearInterval(timer);
  }, [pending, redactions.refresh, productions.refresh]);
  return (
    <>
      <PageHeading
        eyebrow={uiText("REVIEWED DISCLOSURE")}
        title={uiText("Produce with a second look.")}
        text={uiText(
          "Verified derivative copies, fixed review snapshots and a stable Bates registry. Originals stay preserved and are never included in these production packs.",
        )}
      >
        <button
          className="button secondary"
          disabled={!can(matter.role, "review")}
          onClick={() => setCreateRedaction(true)}
        >
          {uiText("Request redaction")}
        </button>
        <button
          className="button primary"
          disabled={!can(matter.role, "export")}
          onClick={() => setCreateProduction(true)}
        >
          <Icon name="export" size={17} />
          {uiText("Propose production")}
        </button>
      </PageHeading>
      <div className="notice amber">
        <Icon name="shield" size={19} />
        <span>
          {uiText(
            "A different current matter lead or attorney must approve each redaction and production. Privilege, review and integrity checks are repeated before delivery. Preservation holds remain disclosed; they do not authorize disclosure.",
          )}
        </span>
      </div>
      {can(matter.role, "review") ? (
        <section className="section">
          <div className="section-heading">
            <div>
              <h2>{uiText("Redaction review")}</h2>
              <p className="muted">
                {uiText(
                  "Inspect the generated sanitized derivative before a separate approval.",
                )}
              </p>
            </div>
            <button
              className="button secondary compact"
              onClick={redactions.refresh}
            >
              {uiText("Refresh redactions")}
            </button>
          </div>
          <ErrorBox error={redactions.error} retry={redactions.refresh} />
          {redactions.loading ? (
            <Loading />
          ) : (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{uiText("Evidence")}</th>
                    <th>{uiText("Derivative")}</th>
                    <th>{uiText("State")}</th>
                    <th>{uiText("Preserved hash")}</th>
                    <th>
                      <span className="sr-only">
                        {uiText("Redaction action")}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {redactions.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link
                          className="mono"
                          href={`/app/matters/${matter.id}/evidence/${item.evidence_id}`}
                        >
                          {item.evidence_id}
                        </Link>
                        <small className="block">{item.reason}</small>
                      </td>
                      <td>{label(item.kind)}</td>
                      <td>
                        <Badge value={item.state} />
                      </td>
                      <td className="mono">
                        {item.sha256
                          ? `${item.sha256.slice(0, 18)}…`
                          : uiText("Awaiting derivative")}
                      </td>
                      <td>
                        <button
                          className="button secondary compact"
                          onClick={() => setRedactionId(item.id)}
                        >
                          {uiText("Inspect redaction")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!redactions.data?.items.length && (
                <Empty
                  icon="review"
                  title={uiText("No redaction requests")}
                  text={uiText(
                    "Select exact text offsets or PDF page regions. Sanitized derivatives are generated and checked separately from immutable originals.",
                  )}
                />
              )}
            </div>
          )}
          <Pagination
            previous={
              redactionHistory.length
                ? () => {
                    const pages = [...redactionHistory];
                    setRedactionCursor(pages.pop() || null);
                    setRedactionHistory(pages);
                  }
                : undefined
            }
            next={
              redactions.data?.next_cursor
                ? () => {
                    setRedactionHistory([...redactionHistory, redactionCursor]);
                    setRedactionCursor(redactions.data!.next_cursor);
                  }
                : undefined
            }
          />
        </section>
      ) : (
        <div className="notice subtle">
          <Icon name="lock" size={17} />
          {uiText("Your matter role does not allow redaction review.")}
        </div>
      )}
      {can(matter.role, "export") && (
        <section className="section">
          <div className="section-heading">
            <div>
              <h2>{uiText("Production packs")}</h2>
              <p className="muted">
                {uiText(
                  "At most 200 reviewed items per pack. Flattened PDF copies or verified UTF-8 text, manifest and CSV/DAT/OPT load files.",
                )}
              </p>
            </div>
            <button
              className="button secondary compact"
              onClick={productions.refresh}
            >
              {uiText("Refresh productions")}
            </button>
          </div>
          <ErrorBox error={productions.error} retry={productions.refresh} />
          {productions.loading ? (
            <Loading />
          ) : (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{uiText("Pack")}</th>
                    <th>{uiText("Scope")}</th>
                    <th>{uiText("State")}</th>
                    <th>{uiText("Bates prefix")}</th>
                    <th>
                      <span className="sr-only">
                        {uiText("Production action")}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {productions.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.reason}</strong>
                        <small className="block mono">{item.id}</small>
                      </td>
                      <td>
                        {uiText("{0} items", {
                          "0": number(item.evidence_ids.length),
                        })}
                      </td>
                      <td>
                        <Badge value={item.state} />
                        <ManifestSigningStatus
                          state={item.state}
                          counts={item.counts}
                        />
                      </td>
                      <td className="mono">{item.bates_prefix}</td>
                      <td>
                        <button
                          className="button secondary compact"
                          onClick={() => setProductionId(item.id)}
                        >
                          {uiText("Inspect pack")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!productions.data?.items.length && (
                <Empty
                  icon="export"
                  title={uiText("No proposed productions")}
                  text={uiText(
                    "Propose a reviewed evidence snapshot and approved redactions. The pack is generated only after separate attorney or matter-lead approval.",
                  )}
                />
              )}
            </div>
          )}
          <Pagination
            previous={
              productionHistory.length
                ? () => {
                    const pages = [...productionHistory];
                    setProductionCursor(pages.pop() || null);
                    setProductionHistory(pages);
                  }
                : undefined
            }
            next={
              productions.data?.next_cursor
                ? () => {
                    setProductionHistory([
                      ...productionHistory,
                      productionCursor,
                    ]);
                    setProductionCursor(productions.data!.next_cursor);
                  }
                : undefined
            }
          />
        </section>
      )}
      {createRedaction && (
        <RedactionRequest
          caseId={matter.id}
          initialId={params.get("evidence_id") || ""}
          close={() => setCreateRedaction(false)}
          done={(id) => {
            setCreateRedaction(false);
            redactions.refresh();
            setRedactionId(id);
          }}
        />
      )}
      {createProduction && (
        <ProductionRequest
          caseId={matter.id}
          close={() => setCreateProduction(false)}
          done={(id) => {
            setCreateProduction(false);
            productions.refresh();
            setProductionId(id);
          }}
        />
      )}
      {redactionId && (
        <RedactionReview
          caseId={matter.id}
          id={redactionId}
          user={user}
          canApprove={can(matter.role, "privilege")}
          close={() => setRedactionId(null)}
          changed={redactions.refresh}
        />
      )}
      {productionId && (
        <ProductionReview
          caseId={matter.id}
          id={productionId}
          user={user}
          canApprove={can(matter.role, "privilege")}
          close={() => setProductionId(null)}
          changed={productions.refresh}
        />
      )}
    </>
  );
}

function RedactionRequest({
  caseId,
  initialId,
  close,
  done,
}: {
  caseId: string;
  initialId: string;
  close: () => void;
  done: (id: string) => void;
}) {
  const live = useMountedRef();
  const [draftId, setDraftId] = useState(initialId),
    [id, setId] = useState(initialId),
    [kind, setKind] = useState<"text" | "pdf">("text"),
    [ranges, setRanges] = useState<Range[]>([]),
    [regions, setRegions] = useState<Region[]>([]),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const item = useResource<EvidenceDetail>(
    id ? `/cases/${caseId}/evidence/${id}` : null,
  );
  const content = useResource<{ text: string; artifact_version: number }>(
    id && kind === "text" ? `/cases/${caseId}/evidence/${id}/content` : null,
  );
  const [selectedContent, setSelectedContent] = useState<{
    text: string;
    artifact_version: number;
  } | null>(null);
  const sourceContent = selectedContent || content.data;
  const textRef = useRef<HTMLTextAreaElement>(null),
    text = sourceContent?.text || "",
    characters = Array.from(text);
  return (
    <Modal title={uiText("Request a sanitized redaction")} close={close} wide>
      <div className="evidence-lookup">
        <label>
          {uiText("Evidence ID")}
          <input
            value={draftId}
            disabled={busy}
            onChange={(event) => setDraftId(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="button secondary"
          disabled={busy || !draftId.trim()}
          onClick={() => {
            setId(draftId.trim());
            setRanges([]);
            setRegions([]);
            setSelectedContent(null);
            setError(null);
          }}
        >
          {uiText("Load evidence")}
        </button>
      </div>
      <ErrorBox error={item.error || content.error || error} />
      {(item.loading || content.loading) && <Loading />}
      {item.data && (
        <form
          inert={busy}
          aria-busy={busy}
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setBusy(true);
            setError(null);
            try {
              const result = await post<{ id: string }>(
                `/cases/${caseId}/redactions`,
                {
                  evidence_id: id,
                  kind,
                  reason: form.get("reason"),
                  ...(kind === "text"
                    ? {
                        ranges,
                        expected_text_version: sourceContent?.artifact_version,
                      }
                    : { regions }),
                },
              );
              if (live.current) done(result.id);
            } catch (error) {
              if (live.current) setError(error);
            } finally {
              if (live.current) setBusy(false);
            }
          }}
        >
          <h3>{item.data.title}</h3>
          <p className="field-help">
            {uiText("Original SHA-256:") + " "}
            <code>{item.data.sha256}</code>
          </p>
          <label>
            {uiText("Derivative type")}
            <select
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as "text" | "pdf");
                setRanges([]);
                setRegions([]);
                setSelectedContent(null);
              }}
            >
              <option value="text">{uiText("UTF-8 extracted text")}</option>
              <option value="pdf" disabled={item.data.type !== "pdf"}>
                {uiText("Flattened PDF pages")}
              </option>
            </select>
          </label>
          {kind === "text" ? (
            <>
              <label>
                {uiText("Immutable extracted text · version")}{" "}
                {sourceContent?.artifact_version || "—"}
                <textarea
                  className="redaction-source-text"
                  ref={textRef}
                  readOnly
                  value={text}
                  rows={10}
                />
              </label>
              <button
                type="button"
                className="button secondary compact"
                disabled={!text || ranges.length >= 200}
                onClick={() => {
                  const field = textRef.current;
                  if (
                    !field ||
                    !sourceContent ||
                    field.selectionEnd <= field.selectionStart
                  ) {
                    setError(
                      new Error(
                        "Select the exact source text you want to redact first.",
                      ),
                    );
                    return;
                  }
                  const range = {
                    start: Array.from(text.slice(0, field.selectionStart))
                      .length,
                    end: Array.from(text.slice(0, field.selectionEnd)).length,
                  };
                  setSelectedContent({
                    text: sourceContent.text,
                    artifact_version: sourceContent.artifact_version,
                  });
                  setRanges([...ranges, range]);
                  setError(null);
                }}
              >
                {uiText("Add selected text range")}
              </button>
              <div className="redaction-selections">
                {ranges.map((range, index) => (
                  <div key={index}>
                    <span>
                      <strong>
                        {uiText("Characters {0}–{1}", {
                          "0": range.start,
                          "1": range.end,
                        })}
                      </strong>
                      <small className="block">
                        {characters
                          .slice(range.start, range.end)
                          .join("")
                          .slice(0, 180)}
                      </small>
                    </span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={uiText("Remove text range {0}", {
                        "0": index + 1,
                      })}
                      onClick={() => {
                        const remaining = ranges.filter((_, i) => i !== index);
                        setRanges(remaining);
                        if (!remaining.length) setSelectedContent(null);
                      }}
                    >
                      <Icon name="close" size={15} />
                    </button>
                  </div>
                ))}
              </div>
              <p className="field-help">
                {uiText(
                  "Ranges use zero-based Unicode character offsets; the end is exclusive. The server binds them to the verified extracted-text version.",
                )}
              </p>
            </>
          ) : (
            <>
              <PdfRegionSelector
                caseId={caseId}
                evidenceId={id}
                originalHash={item.data.sha256}
                regions={regions}
                change={setRegions}
              />
              <div className="notice subtle">
                <Icon name="file" size={17} />
                <span>
                  {uiText(
                    "Use normalized page coordinates with the top-left as origin. For example x=0.1, y=0.2, width=0.3 and height=0.1. Inspect the sanitized draft and the original before approval. PDF processing is limited to 50 pages and 50 MB.",
                  )}
                </span>
              </div>
              <a
                className="text-link"
                href={`/api/v1/cases/${caseId}/evidence/${id}/original`}
              >
                {uiText("Download original for coordinate review")}
              </a>
              <div className="redaction-regions">
                {regions.map((region, index) => (
                  <div className="region-row" key={index}>
                    {(["page", "x", "y", "width", "height"] as const).map(
                      (field) => (
                        <label key={field}>
                          {label(field)}
                          <input
                            type="number"
                            aria-label={uiText("Region {0} {1}", {
                              "0": index + 1,
                              "1": label(field),
                            })}
                            value={region[field]}
                            min={
                              field === "page"
                                ? 1
                                : field === "width" || field === "height"
                                  ? 0.001
                                  : 0
                            }
                            max={field === "page" ? 50 : 1}
                            step={field === "page" ? 1 : 0.001}
                            required
                            onChange={(event) =>
                              setRegions(
                                regions.map((value, i) =>
                                  i === index
                                    ? {
                                        ...value,
                                        [field]: Number(event.target.value),
                                      }
                                    : value,
                                ),
                              )
                            }
                          />
                        </label>
                      ),
                    )}
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={uiText("Remove PDF region {0}", {
                        "0": index + 1,
                      })}
                      onClick={() =>
                        setRegions(regions.filter((_, i) => i !== index))
                      }
                    >
                      <Icon name="close" size={15} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="button secondary compact"
                disabled={regions.length >= 200}
                onClick={() =>
                  setRegions([
                    ...regions,
                    { page: 1, x: 0.1, y: 0.1, width: 0.3, height: 0.1 },
                  ])
                }
              >
                {uiText("Add PDF region")}
              </button>
            </>
          )}
          <label>
            {uiText("Redaction reason")}
            <textarea
              name="reason"
              required
              minLength={3}
              maxLength={2000}
              rows={3}
            />
          </label>
          <div className="form-actions">
            <button type="button" className="button secondary" onClick={close}>
              {uiText("Cancel")}
            </button>
            <button
              className="button primary"
              disabled={
                busy ||
                (kind === "text"
                  ? !ranges.length || !content.data
                  : !regions.length)
              }
            >
              {busy ? uiText("Requesting…") : uiText("Generate redacted draft")}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function ProductionRequest({
  caseId,
  close,
  done,
}: {
  caseId: string;
  close: () => void;
  done: (id: string) => void;
}) {
  const live = useMountedRef();
  const [redactionCursor, setRedactionCursor] = useState<string | null>(null),
    [availableRedactions, setAvailableRedactions] = useState<Redaction[]>([]);
  const sets = useResource<{
      items: { id: string; name: string; count: number }[];
    }>(`/cases/${caseId}/review-sets`),
    redactions = useResource<{
      items: Redaction[];
      next_cursor: string | null;
    }>(
      `/cases/${caseId}/redactions?limit=100${redactionCursor ? `&cursor=${encodeURIComponent(redactionCursor)}` : ""}`,
    );
  useEffect(() => {
    if (redactions.data)
      setAvailableRedactions((current) => [
        ...new Map(
          [...current, ...redactions.data!.items].map((item) => [
            item.id,
            item,
          ]),
        ).values(),
      ]);
  }, [redactions.data]);
  const [scope, setScope] = useState("ids"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal title={uiText("Propose a derived production pack")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const approved =
            availableRedactions.filter((item) =>
              form.getAll("redaction").includes(item.id),
            ) || [];
          const mapping: Record<string, string> = {};
          for (const item of approved) {
            if (mapping[item.evidence_id]) {
              setError(
                new Error(
                  "Select only one approved redaction for each evidence item.",
                ),
              );
              return;
            }
            mapping[item.evidence_id] = item.id;
          }
          setBusy(true);
          setError(null);
          try {
            const result = await post<{ id: string }>(
              `/cases/${caseId}/productions`,
              {
                ...(scope === "set"
                  ? { review_set_id: form.get("review_set_id") }
                  : {
                      evidence_ids: String(form.get("evidence_ids") || "")
                        .split(/[\s,]+/)
                        .filter(Boolean),
                    }),
                redactions: mapping,
                bates_prefix: form.get("bates_prefix"),
                reason: form.get("reason"),
                confirmed: form.get("confirmed") === "on",
              },
            );
            if (live.current) done(result.id);
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error || sets.error || redactions.error} />
        <label>
          {uiText("Production scope")}
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="ids">{uiText("Explicit evidence IDs")}</option>
            <option value="set">{uiText("Fixed review-set snapshot")}</option>
          </select>
        </label>
        {scope === "set" ? (
          <label>
            {uiText("Review set")}
            <select name="review_set_id" required defaultValue="">
              <option value="" disabled>
                {uiText("Choose a review set")}
              </option>
              {sets.data?.items.map((set) => (
                <option
                  key={set.id}
                  value={set.id}
                  disabled={!set.count || set.count > 200}
                >
                  {uiText("{0} · {1} items{2}", {
                    "0": set.name,
                    "1": number(set.count),
                    "2": set.count > 200 ? ` ${uiText("· exceeds limit")}` : "",
                  })}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label>
            {uiText("Evidence IDs")}
            <textarea
              name="evidence_ids"
              required
              rows={4}
              placeholder={uiText("One ID per line, or comma separated")}
            />
          </label>
        )}
        <fieldset className="production-redactions">
          <legend>{uiText("Approved redactions to apply")}</legend>
          {availableRedactions
            .filter((item) => item.state === "approved")
            .map((item) => (
              <label className="checkbox-label" key={item.id}>
                <input name="redaction" value={item.id} type="checkbox" />
                <span>
                  <code>{item.evidence_id}</code>
                  <small className="block">
                    {label(item.kind)} · {item.reason}
                  </small>
                </span>
              </label>
            ))}
          {!availableRedactions.some((item) => item.state === "approved") && (
            <p className="muted">
              {uiText(
                "No approved redactions loaded. Unredacted derivatives may contain sensitive information.",
              )}
            </p>
          )}
          {redactions.loading && (
            <Loading text={uiText("Loading approved redaction choices…")} />
          )}
          {redactions.data?.next_cursor && (
            <button
              type="button"
              className="button secondary compact"
              disabled={redactions.loading}
              onClick={() => setRedactionCursor(redactions.data!.next_cursor)}
            >
              {uiText("Load older redaction records")}
            </button>
          )}
        </fieldset>
        <label>
          {uiText("Bates prefix")}
          <input
            name="bates_prefix"
            defaultValue="CQ"
            required
            pattern="[A-Z][A-Z0-9_-]{0,15}"
            maxLength={16}
          />
        </label>
        <label>
          {uiText("Disclosure reason")}
          <textarea
            name="reason"
            required
            minLength={3}
            maxLength={2000}
            rows={3}
          />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" name="confirmed" required />
          <span>
            {uiText(
              "I confirm the selected evidence scope, applied redactions and requested disclosure. A different matter lead or attorney must approve.",
            )}
          </span>
        </label>
        <div className="notice amber">
          <Icon name="lock" size={17} />
          <span>
            {uiText(
              "Completed human review and privilege none or cleared are required. Packs contain verified text or flattened PDF derivatives, CSV/DAT/OPT load files and a hash manifest; they exclude original native bytes.",
            )}
          </span>
        </div>
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy
              ? uiText("Proposing…")
              : uiText("Propose for separate approval")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Confirmation({
  title,
  path,
  approve,
  close,
  done,
}: {
  title: string;
  path: string;
  approve: boolean;
  close: () => void;
  done: () => void;
}) {
  const live = useMountedRef();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <Modal title={title} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          try {
            await post(path, {
              reason: form.get("reason"),
              ...(approve ? { confirmed: form.get("confirmed") === "on" } : {}),
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
        <label>
          {uiText("Review reason")}
          <textarea
            name="reason"
            required
            minLength={3}
            maxLength={2000}
            rows={3}
          />
        </label>
        {approve && (
          <label className="checkbox-label">
            <input type="checkbox" name="confirmed" required />
            <span>
              {uiText(
                "I separately reviewed this disclosure and confirm approval. The server will recheck evidence, human review and permissions.",
              )}
            </span>
          </label>
        )}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={close}>
            {uiText("Back")}
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Saving…") : title}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function RedactionReview({
  caseId,
  id,
  user,
  canApprove,
  close,
  changed,
}: {
  caseId: string;
  id: string;
  user: User;
  canApprove: boolean;
  close: () => void;
  changed: () => void;
}) {
  const detail = useResource<Redaction>(`/cases/${caseId}/redactions/${id}`),
    [action, setAction] = useState<"approve" | "reject" | null>(null);
  const row = detail.data;
  useEffect(() => {
    if (!row || !["pending", "running"].includes(row.state)) return;
    const timer = setInterval(detail.refresh, 2000);
    return () => clearInterval(timer);
  }, [row, detail.refresh]);
  const refresh = () => {
    detail.refresh();
    changed();
  };
  return (
    <Modal title={uiText("Inspect redacted derivative")} close={close} wide>
      <ErrorBox error={detail.error} retry={detail.refresh} />
      {detail.loading && !row ? (
        <Loading />
      ) : (
        row && (
          <>
            <div className="section-heading">
              <div>
                <Badge value={row.state} />
                <h3 className="mono">{row.evidence_id}</h3>
                <p className="muted">{row.reason}</p>
              </div>
              <Link
                className="text-link"
                href={`/app/matters/${caseId}/evidence/${row.evidence_id}`}
              >
                {uiText("Inspect source") + " "}
                <Icon name="arrow" size={14} />
              </Link>
            </div>
            {row.error && (
              <div className="notice red" role="alert">
                {row.error_code}: {row.error}
              </div>
            )}
            {["ready_for_review", "approved"].includes(row.state) && (
              <SanitizedPreview caseId={caseId} row={row} />
            )}
            {row.sha256 && (
              <>
                <h3>{uiText("Sanitized derivative SHA-256")}</h3>
                <code className="hash-block">{row.sha256}</code>
                <p className="field-help">
                  {uiText(
                    "{0} · verified derivative, original preserved separately.",
                    { "0": bytes(row.byte_size) },
                  )}
                </p>
              </>
            )}
            <details className="audit-metadata">
              <summary>{uiText("Selection and verification results")}</summary>
              <pre>
                {JSON.stringify(
                  { selection: row.selection, verification: row.verification },
                  null,
                  2,
                )}
              </pre>
            </details>
            {row.state === "ready_for_review" && (
              <>
                <p className="field-help">
                  {uiText(
                    "Review both the sanitized derivative and original. A different matter lead or attorney must approve; the requester cannot approve their own redaction.",
                  )}
                </p>
                <div className="form-actions">
                  <button
                    className="button secondary"
                    onClick={() => setAction("reject")}
                  >
                    {uiText("Reject draft")}
                  </button>
                  <button
                    className="button primary"
                    disabled={!canApprove || row.requested_by === user.id}
                    onClick={() => setAction("approve")}
                  >
                    {uiText("Approve redaction")}
                  </button>
                </div>
              </>
            )}
            {action && (
              <Confirmation
                title={
                  action === "approve"
                    ? uiText("Approve redaction")
                    : uiText("Reject redaction")
                }
                path={`/cases/${caseId}/redactions/${id}/${action}`}
                approve={action === "approve"}
                close={() => setAction(null)}
                done={() => {
                  setAction(null);
                  refresh();
                }}
              />
            )}
          </>
        )
      )}
    </Modal>
  );
}

function SanitizedPreview({ caseId, row }: { caseId: string; row: Redaction }) {
  const [source, setSource] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const controller = new AbortController();
    const submittedSession = csrfToken();
    let url: string | null = null;
    setSource(null);
    setError(null);
    fetch(`/api/v1/cases/${caseId}/redactions/${row.id}/preview`, {
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        controller.signal.throwIfAborted();
        if (!response.ok) {
          if (response.status === 401 && csrfToken() === submittedSession)
            window.dispatchEvent(new Event("cq:unauthorized"));
          const data = await response.json().catch(() => ({}));
          throw new Error(
            data.message ||
              "The sanitized preview is unavailable. Refresh and inspect the reported source or permission change.",
          );
        }
        if (row.kind === "text") return response.text();
        const data = await response.blob();
        controller.signal.throwIfAborted();
        url = URL.createObjectURL(data);
        return url;
      })
      .then((value) => {
        if (!controller.signal.aborted) setSource(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [caseId, row.id, row.kind]);
  return (
    <section className="sanitized-preview">
      <h3>{uiText("Sanitized derivative preview")}</h3>
      <ErrorBox error={error} />
      {source === null && !error ? (
        <Loading text={uiText("Verifying and opening sanitized preview…")} />
      ) : (
        source !== null &&
        (row.kind === "text" ? (
          <pre className="redaction-text-preview">{source}</pre>
        ) : (
          <iframe
            title={uiText("Sanitized flattened PDF derivative")}
            src={source}
            sandbox="allow-same-origin"
            className="redaction-pdf-preview"
          />
        ))
      )}
      <a
        className="text-link"
        href={`/api/v1/cases/${caseId}/redactions/${row.id}/preview`}
      >
        {uiText("Download verified sanitized derivative")}
      </a>
    </section>
  );
}

function ProductionReview({
  caseId,
  id,
  user,
  canApprove,
  close,
  changed,
}: {
  caseId: string;
  id: string;
  user: User;
  canApprove: boolean;
  close: () => void;
  changed: () => void;
}) {
  const detail = useResource<Production>(`/cases/${caseId}/productions/${id}`),
    [approve, setApprove] = useState(false);
  const row = detail.data;
  useEffect(() => {
    if (!row || !["pending", "running"].includes(row.state)) return;
    const timer = setInterval(detail.refresh, 2000);
    return () => clearInterval(timer);
  }, [row, detail.refresh]);
  return (
    <Modal title={uiText("Inspect derived production pack")} close={close} wide>
      <ErrorBox error={detail.error} retry={detail.refresh} />
      {detail.loading && !row ? (
        <Loading />
      ) : (
        row && (
          <>
            <div className="section-heading">
              <div>
                <Badge value={row.state} />
                <h3>{row.reason}</h3>
                <p className="field-help">
                  {uiText("Bates prefix") + " "}
                  <code>{row.bates_prefix}</code> ·{" "}
                  {number(row.evidence_ids.length)}{" "}
                  {" " + uiText("explicit snapshot items ·")}{" "}
                  {Object.keys(row.redactions).length}{" "}
                  {" " + uiText("approved redactions")}
                </p>
              </div>
              {row.state === "completed" && (
                <a
                  className="button primary"
                  href={`/api/v1/cases/${caseId}/productions/${id}/download`}
                >
                  <Icon name="export" size={17} />
                  {uiText("Download verified pack")}
                </a>
              )}
            </div>
            <div className="notice subtle">
              <Icon name="file" size={17} />
              <span>
                {uiText(
                  "Delivery contains derivatives only. CSV/DAT metadata and the tested OPT profile accompany the manifest. Original native files remain excluded; active preservation holds are disclosed in the scope.",
                )}
              </span>
            </div>
            <ManifestSigningStatus
              state={row.state}
              counts={row.counts}
              detail
            />
            <details className="audit-metadata" open>
              <summary>
                {uiText("Scope, processing and hold disclosure")}
              </summary>
              <pre>{JSON.stringify(row.counts, null, 2)}</pre>
            </details>
            <h3>{uiText("Evidence snapshot")}</h3>
            <div className="production-evidence-scope">
              {row.evidence_ids.map((evidence) => (
                <Link
                  key={evidence}
                  href={`/app/matters/${caseId}/evidence/${evidence}`}
                  className="mono"
                >
                  {evidence}
                  {row.redactions[evidence] && (
                    <small>
                      {uiText("· approved redaction {0}", {
                        "0": row.redactions[evidence],
                      })}
                    </small>
                  )}
                </Link>
              ))}
            </div>
            {row.items?.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{uiText("Evidence")}</th>
                      <th>{uiText("Bates beginning")}</th>
                      <th>{uiText("Bates ending")}</th>
                      <th>{uiText("Pages")}</th>
                      <th>{uiText("Produced SHA-256")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.items.map((item) => (
                      <tr key={item.evidence_id}>
                        <td className="mono">{item.evidence_id}</td>
                        <td>{item.begin_bates}</td>
                        <td>{item.end_bates}</td>
                        <td>{number(item.page_count)}</td>
                        <td className="mono hash-cell">
                          {item.produced_sha256}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {row.sha256 && (
              <>
                <h3>{uiText("Production package SHA-256")}</h3>
                <code className="hash-block">{row.sha256}</code>
                <p className="field-help">
                  {uiText(
                    "{0} · hashes and current approval permissions are revalidated at download.",
                    { "0": bytes(row.byte_size) },
                  )}
                </p>
              </>
            )}
            {row.state === "proposed" && (
              <div className="form-actions">
                <p className="field-help">
                  {uiText(
                    "A different current matter lead or attorney must confirm this snapshot. Inspect its evidence and approved redactions before acting.",
                  )}
                </p>
                <button
                  className="button primary"
                  disabled={!canApprove || row.requested_by === user.id}
                  onClick={() => setApprove(true)}
                >
                  {uiText("Approve production")}
                </button>
              </div>
            )}
            {approve && (
              <Confirmation
                title={uiText("Approve production")}
                path={`/cases/${caseId}/productions/${id}/approve`}
                approve
                close={() => setApprove(false)}
                done={() => {
                  setApprove(false);
                  detail.refresh();
                  changed();
                }}
              />
            )}
          </>
        )
      )}
    </Modal>
  );
}
