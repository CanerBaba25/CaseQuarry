"use client";

import Link from "next/link";
import { useState } from "react";
import { label, number, post } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { Badge, Empty, ErrorBox, Icon, Loading } from "./ui";

type Citation = {
  evidence_id: string;
  span_id: string | null;
  page: number | null;
  char_start: number;
  char_end: number;
  artifact_version: number;
  artifact_sha256: string;
  original_sha256: string;
};
type Provenance = {
  evidence_id: string;
  title: string;
  original_sha256: string;
  artifact_sha256: string;
  artifact_version: number;
  parser_state: string;
  text_truncated: boolean;
};
type Coverage = Record<string, number | boolean>;
type Entities = {
  items: {
    kind: string;
    text: string;
    char_start: number;
    char_end: number;
    citations: Citation[];
  }[];
  coverage: Coverage;
  limits: string[];
};
type Near = {
  items: (Provenance & { score: number; citations: Citation[] })[];
  coverage: Coverage;
  limits: string[];
};
type Comparison = {
  left: Provenance;
  right: Provenance;
  segments: {
    kind: string;
    left_text: string;
    right_text: string;
    left_start: number;
    left_end: number;
    right_start: number;
    right_end: number;
    citations: Citation[];
  }[];
  coverage: Coverage;
  limits: string[];
};

export default function SourceInvestigations({
  caseId,
  id,
  open,
}: {
  caseId: string;
  id: string;
  open: (id: string) => void;
}) {
  const entities = useResource<Entities>(
    `/cases/${caseId}/evidence/${id}/entities`,
  );
  const [near, setNear] = useState<Near | null>(null),
    [comparison, setComparison] = useState<Comparison | null>(null),
    [rightId, setRightId] = useState(""),
    [threshold, setThreshold] = useState(0.75),
    [busy, setBusy] = useState<string | null>(null),
    [error, setError] = useState<unknown>(null),
    [changesOnly, setChangesOnly] = useState(false);
  return (
    <div className="source-investigations">
      <div className="notice amber">
        <Icon name="review" size={17} />
        <span>
          Source-backed candidates require human interpretation. They do not
          merge identities, establish facts or change evidence review decisions.
        </span>
      </div>
      <h3>Anchored rule candidates</h3>
      <p className="field-help">
        Email addresses, dates, currency amounts and labeled invoice numbers
        from a verified text prefix. A candidate occurrence is not a confirmed
        entity or legal event.
      </p>
      <ErrorBox error={entities.error} retry={entities.refresh} />
      {entities.loading ? (
        <Loading text="Verifying candidate source locations…" />
      ) : (
        entities.data && (
          <>
            {entities.data.items.length ? (
              <div className="entity-candidates">
                {entities.data.items.map((item, index) => (
                  <div key={`${item.char_start}-${item.kind}-${index}`}>
                    <Badge value={item.kind} />
                    <strong>{item.text}</strong>
                    <small>
                      Characters {item.char_start}–{item.char_end}
                    </small>
                    <CitationLinks caseId={caseId} citations={item.citations} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                No anchored rule matches in the retrieved text prefix.
              </p>
            )}
            <OperationCoverage
              coverage={entities.data.coverage}
              limits={entities.data.limits}
            />
          </>
        )
      )}
      <section className="investigation-operation">
        <h3>Near-duplicate candidates</h3>
        <p className="field-help">
          Compare three-word shingles against at most 100 eligible source
          occurrences. Byte-exact originals are excluded. Similarity is a
          text-overlap score, not a probability or verified relationship.
        </p>
        <form
          className="candidate-search-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy("near");
            setError(null);
            setNear(null);
            try {
              setNear(
                await post(`/cases/${caseId}/evidence/${id}/near-duplicates`, {
                  threshold,
                  candidate_limit: 100,
                  limit: 20,
                }),
              );
            } catch (error) {
              setError(error);
            } finally {
              setBusy(null);
            }
          }}
        >
          <label>
            Minimum text similarity
            <input
              type="number"
              min={0.1}
              max={1}
              step={0.05}
              value={threshold}
              required
              onChange={(event) => setThreshold(Number(event.target.value))}
            />
          </label>
          <button className="button secondary compact" disabled={Boolean(busy)}>
            {busy === "near" ? "Comparing…" : "Find near-duplicate candidates"}
          </button>
        </form>
        {near && (
          <>
            {near.items.length ? (
              <div className="near-candidate-list">
                {near.items.map((item) => (
                  <div key={item.evidence_id}>
                    <button
                      className="text-link"
                      onClick={() => open(item.evidence_id)}
                    >
                      {item.title}
                      <Icon name="arrow" size={13} />
                    </button>
                    <span>
                      {(item.score * 100).toFixed(1)}% word-shingle similarity
                    </span>
                    <small className="mono">{item.evidence_id}</small>
                    <div className="button-row">
                      <button
                        className="button secondary compact"
                        onClick={() => {
                          setRightId(item.evidence_id);
                          setComparison(null);
                        }}
                      >
                        Use in comparison
                      </button>
                      <Badge value="Requires human review" tone="amber" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                No verified candidates met this threshold in the scanned subset.
              </p>
            )}
            <OperationCoverage coverage={near.coverage} limits={near.limits} />
          </>
        )}
      </section>
      <section className="investigation-operation">
        <h3>Compare extracted text</h3>
        <p className="field-help">
          A bounded word-and-whitespace diff with hashes and exact source
          ranges. It does not infer which document came first or explain why
          text changed.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy("compare");
            setError(null);
            setComparison(null);
            try {
              setComparison(
                await post(`/cases/${caseId}/compare`, {
                  left_id: id,
                  right_id: rightId.trim(),
                }),
              );
            } catch (error) {
              setError(error);
            } finally {
              setBusy(null);
            }
          }}
        >
          <label>
            Other evidence ID
            <input
              value={rightId}
              required
              onChange={(event) => setRightId(event.target.value)}
              placeholder="Paste an evidence ID or use a candidate above"
            />
          </label>
          <button
            className="button secondary compact"
            disabled={Boolean(busy) || !rightId.trim()}
          >
            {busy === "compare" ? "Comparing…" : "Compare these sources"}
          </button>
        </form>
        {comparison && (
          <>
            <div className="compare-source-pair">
              <SourceProvenance
                side="Current source"
                source={comparison.left}
              />
              <SourceProvenance side="Other source" source={comparison.right} />
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={changesOnly}
                onChange={(event) => setChangesOnly(event.target.checked)}
              />
              <span>Show changed segments only</span>
            </label>
            <div className="diff-segments">
              {comparison.segments
                .filter((segment) => !changesOnly || segment.kind !== "equal")
                .map((segment, index) => (
                  <div key={index} className={`diff-segment ${segment.kind}`}>
                    <Badge value={segment.kind} />
                    <div className="diff-columns">
                      <div>
                        <small>
                          Current · chars {segment.left_start}–
                          {segment.left_end}
                        </small>
                        <pre>
                          {segment.left_text || "No text in this range"}
                        </pre>
                      </div>
                      <div>
                        <small>
                          Other · chars {segment.right_start}–
                          {segment.right_end}
                        </small>
                        <pre>
                          {segment.right_text || "No text in this range"}
                        </pre>
                      </div>
                    </div>
                    <CitationLinks
                      caseId={caseId}
                      citations={segment.citations}
                    />
                  </div>
                ))}
            </div>
            {changesOnly &&
              !comparison.segments.some(
                (segment) => segment.kind !== "equal",
              ) && (
                <Empty
                  icon="file"
                  title="No differences in the compared scope"
                  text="The retrieved text segments match. Review the operation coverage before treating this as a full-document comparison."
                />
              )}
            <OperationCoverage
              coverage={comparison.coverage}
              limits={comparison.limits}
            />
          </>
        )}
      </section>
      <ErrorBox error={error} />
    </div>
  );
}

function SourceProvenance({
  side,
  source,
}: {
  side: string;
  source: Provenance;
}) {
  return (
    <div>
      <small className="eyebrow">{side}</small>
      <strong>{source.title}</strong>
      <small className="mono">
        {source.evidence_id} · text v{source.artifact_version}
      </small>
      <details className="audit-metadata">
        <summary>Verified source hashes</summary>
        <code className="hash-block">
          Original: {source.original_sha256}
          <br />
          Artifact: {source.artifact_sha256}
        </code>
      </details>
    </div>
  );
}
function CitationLinks({
  caseId,
  citations,
}: {
  caseId: string;
  citations: Citation[];
}) {
  return (
    <div className="candidate-citations">
      {citations.map((citation, index) => (
        <Link
          key={index}
          className="text-link"
          href={`/app/matters/${caseId}/evidence/${citation.evidence_id}?version=${citation.artifact_version}${citation.span_id ? `#span-${citation.span_id}` : ""}`}
          title={`Original SHA-256 ${citation.original_sha256}; artifact SHA-256 ${citation.artifact_sha256}`}
        >
          <Icon name="file" size={12} />
          {citation.page
            ? `Page ${citation.page}`
            : `Chars ${citation.char_start}–${citation.char_end}`}{" "}
          · v{citation.artifact_version}
        </Link>
      ))}
    </div>
  );
}
function OperationCoverage({
  coverage,
  limits,
}: {
  coverage: Coverage;
  limits: string[];
}) {
  return (
    <details className="operation-coverage" open>
      <summary>Operation coverage and limitations</summary>
      <dl>
        {Object.entries(coverage).map(([key, value]) => (
          <div key={key}>
            <dt>{label(key)}</dt>
            <dd>
              {typeof value === "boolean"
                ? value
                  ? "Yes"
                  : "No"
                : number(value)}
            </dd>
          </div>
        ))}
      </dl>
      <ul>
        {limits.map((limit, index) => (
          <li key={index}>{limit}</li>
        ))}
      </ul>
    </details>
  );
}
