"use client";
import { uiText, type MessageKey } from "@/lib/i18n";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  bytes,
  date,
  getDisplayTimeZone,
  uiLabel as label,
  number,
  post,
} from "@/lib/api";
import { useMountedRef, useResource } from "@/lib/hooks";
import type {
  AuditEvent,
  ExportRecord,
  ImportBatch,
  Matter,
  Person,
  SearchSpec,
  Source,
  Stats,
  TimelineItem,
  User,
} from "@/lib/types";
import { can } from "@/lib/permissions";
import { MatterTeam } from "./team";
import ImportCapabilities from "./import-capabilities";
import { Badge, Empty, ErrorBox, Icon, Loading, Modal } from "./ui";

export function PageHeading({
  eyebrow,
  title,
  text,
  children,
}: {
  eyebrow: string;
  title: string;
  text: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {children}
    </div>
  );
}

export function Coverage({
  processing,
  total,
}: {
  processing: Record<string, number>;
  total?: number;
}) {
  const keys = [
    "indexed",
    "pending",
    "stored",
    "partial",
    "failed",
    "unsupported",
    "quarantined",
    "locked",
  ];
  const excluded = keys
    .filter((key) => !["indexed"].includes(key))
    .reduce((sum, key) => sum + (processing[key] || 0), 0);
  return (
    <div className="coverage-card">
      <div className="section-heading">
        <h3>{uiText("Data coverage")}</h3>
        <Badge
          value={excluded ? "Requires attention" : "Indexed records available"}
          tone={excluded ? "amber" : "green"}
        />
      </div>
      <p className="muted">
        {uiText(
          "{0}Text search depends on extracted content. Preserved items remain available by metadata.",
          {
            "0":
              total !== undefined
                ? `${uiText("{0} preserved evidence items.", {
                    "0": number(total),
                  })} `
                : "",
          },
        )}
      </p>
      <div className="coverage-grid">
        {keys.map((key) => (
          <div key={key}>
            <span className={`coverage-dot ${key}`} />
            <span>{label(key)}</span>
            <strong>{number(processing[key])}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MatterOverview({ matter }: { matter: Matter }) {
  const stats = useResource<Stats>(`/cases/${matter.id}/stats`);
  const data = stats.data;
  return (
    <>
      <PageHeading
        eyebrow={matter.matter_number}
        title={matter.title}
        text={`${matter.client || uiText("Client not specified")}${matter.jurisdiction ? ` · ${matter.jurisdiction}` : ""}`}
      >
        <Link
          className="button primary"
          href={`/app/matters/${matter.id}/sources`}
        >
          <Icon name="upload" size={18} />
          {uiText("Import evidence")}
        </Link>
      </PageHeading>
      {matter.archived_at && (
        <div className="notice amber">
          <Icon name="alert" />
          {uiText(
            "This matter is archived. Restore it in matter settings before continuing work.",
          )}
        </div>
      )}
      <ErrorBox error={stats.error} retry={stats.refresh} />
      {stats.loading && !data ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="metric-grid">
              <Metric
                icon="file"
                value={number(data.evidence_items)}
                name="Evidence items"
                detail={uiText("{0} source occurrences", {
                  "0": number(data.source_occurrences),
                })}
              />
              <Metric
                icon="search"
                value={number(data.indexed)}
                name="Searchable items"
                detail={uiText("Extracted and indexed content")}
              />
              <Metric
                icon="review"
                value={number(data.reviewed)}
                name="Human reviewed"
                detail={uiText("{0}% of preserved evidence", {
                  "0": number(
                    data.evidence_items
                      ? Math.round((data.reviewed / data.evidence_items) * 100)
                      : 0,
                  ),
                })}
              />
              <Metric
                icon="shield"
                value={bytes(data.total_bytes)}
                name="Preserved originals"
                detail={uiText(
                  "{0} unique objects · {1} duplicate occurrences",
                  {
                    "0": number(data.unique_objects),
                    "1": number(data.duplicates),
                  },
                )}
              />
            </div>
            <div className="overview-grid">
              <section className="panel">
                <div className="panel-heading spread">
                  <div>
                    <span className="eyebrow">{uiText("THE COLLECTION")}</span>
                    <h2>{uiText("Your evidence, at a glance.")}</h2>
                  </div>
                  <Link
                    href={`/app/matters/${matter.id}/explorer`}
                    className="text-link"
                  >
                    {uiText("Explore evidence")}
                    <Icon name="arrow" size={16} />
                  </Link>
                </div>
                {data.evidence_items === 0 ? (
                  <Empty
                    icon="upload"
                    title={uiText("Ready for the first source.")}
                    text={uiText(
                      "Import emails or documents. CaseQuarry preserves original bytes and reports any extraction gaps.",
                    )}
                  >
                    <Link
                      href={`/app/matters/${matter.id}/sources`}
                      className="button secondary"
                    >
                      {uiText("Import files")}
                      <Icon name="arrow" size={16} />
                    </Link>
                  </Empty>
                ) : (
                  <div className="type-breakdown">
                    {data.types.map((item) => (
                      <Link
                        key={item.key}
                        href={`/app/matters/${matter.id}/explorer?type=${encodeURIComponent(item.key)}`}
                        className="type-row"
                      >
                        <span className="type-icon">
                          <Icon
                            name={item.key === "email" ? "email" : "file"}
                          />
                        </span>
                        <div>
                          <span>{label(item.key)}</span>
                          <div className="bar-track">
                            <span
                              style={{
                                width: `${Math.max(1, (item.count / data.evidence_items) * 100)}%`,
                              }}
                            />
                          </div>
                        </div>
                        <strong>{number(item.count)}</strong>
                        <Icon name="chevron" size={16} />
                      </Link>
                    ))}
                  </div>
                )}
                <div className="panel-footer">
                  <Icon name="lock" size={16} />
                  <span>
                    {uiText(
                      "Source objects are kept separately from derived text.",
                    )}
                  </span>
                </div>
              </section>
              <section className="panel review-progress">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">{uiText("REVIEW PROGRESS")}</span>
                    <h2>{uiText("Every decision, recorded.")}</h2>
                  </div>
                </div>
                <div
                  className="progress-ring"
                  style={
                    {
                      "--progress": `${data.evidence_items ? (data.reviewed / data.evidence_items) * 100 : 0}%`,
                    } as React.CSSProperties
                  }
                >
                  <div>
                    <strong>
                      {data.evidence_items
                        ? Math.round(
                            (data.reviewed / data.evidence_items) * 100,
                          )
                        : 0}
                      <small>%</small>
                    </strong>
                    <span>{uiText("reviewed")}</span>
                  </div>
                </div>
                <div className="review-legend">
                  {data.review_status.map((item) => (
                    <div key={item.key}>
                      <Badge value={item.key} />
                      <strong>{number(item.count)}</strong>
                    </div>
                  ))}
                </div>
                <Link
                  href={`/app/matters/${matter.id}/review`}
                  className="button secondary full-width"
                >
                  {uiText("Open review queue")}
                  <Icon name="arrow" size={17} />
                </Link>
              </section>
            </div>
            <div className="overview-lower">
              <Coverage
                processing={data.processing}
                total={data.evidence_items}
              />
              <section className="panel activity-panel">
                <div className="section-heading">
                  <h3>{uiText("Recent activity")}</h3>
                  <Link
                    href={`/app/matters/${matter.id}/audit`}
                    className="text-link"
                  >
                    {uiText("View audit trail")}
                    <Icon name="arrow" size={15} />
                  </Link>
                </div>
                {data.recent_activity.length ? (
                  <div className="activity-list">
                    {data.recent_activity.slice(0, 7).map((item) => (
                      <div key={item.id}>
                        <span className="activity-dot" />
                        <div>
                          <strong>{label(item.event_type)}</strong>
                          <small>
                            {date(item.timestamp || item.created_at, true)}
                          </small>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    {uiText("Activity will appear here as your team works.")}
                  </p>
                )}
              </section>
            </div>
          </>
        )
      )}
    </>
  );
}

function Metric({
  icon,
  value,
  name,
  detail,
}: {
  icon: string;
  value: string;
  name: MessageKey;
  detail: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">
        <span>{uiText(name)}</span>
        <Icon name={icon} size={18} />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export function SourcesPage({
  matter,
  batchId,
}: {
  matter: Matter;
  batchId?: string;
}) {
  const sources = useResource<{ items: Source[] }>(
      `/cases/${matter.id}/sources`,
    ),
    imports = useResource<{ items: ImportBatch[] }>(
      `/cases/${matter.id}/imports`,
    );
  const [upload, setUpload] = useState(false),
    [sourceModal, setSourceModal] = useState(false),
    [activeBatch, setActiveBatch] = useState<string | null>(batchId || null);
  const selected = useResource<ImportBatch>(
    activeBatch ? `/cases/${matter.id}/imports/${activeBatch}` : null,
  );
  const [actionError, setActionError] = useState<unknown>(null),
    [actionBusy, setActionBusy] = useState(false);
  const batchScope = useRef(activeBatch);
  batchScope.current = activeBatch;
  const live = useMountedRef();
  const active =
    imports.data?.items.some((item) =>
      ["pending", "queued", "running", "processing", "stored"].includes(
        item.state.toLowerCase(),
      ),
    ) || false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(imports.refresh, 2500);
    return () => clearInterval(timer);
  }, [active, imports.refresh]);
  useEffect(() => {
    if (
      !selected.data ||
      !["pending", "queued", "running", "processing", "stored"].includes(
        selected.data.state.toLowerCase(),
      )
    )
      return;
    const timer = setInterval(selected.refresh, 2500);
    return () => clearInterval(timer);
  }, [selected.data, selected.refresh]);
  async function action(name: string) {
    if (!activeBatch) return;
    const submittedBatch = activeBatch;
    setActionBusy(true);
    setActionError(null);
    try {
      await post(`/cases/${matter.id}/imports/${activeBatch}/${name}`);
      if (!live.current || batchScope.current !== submittedBatch) return;
      selected.refresh();
      imports.refresh();
    } catch (error) {
      if (live.current && batchScope.current === submittedBatch)
        setActionError(error);
    } finally {
      if (live.current) setActionBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow={uiText("SOURCE INVENTORY")}
        title={uiText("A traceable record.")}
        text={uiText(
          "Preserve where evidence came from, then follow every import through processing.",
        )}
      >
        <button
          className="button primary"
          onClick={() => setUpload(true)}
          disabled={Boolean(matter.archived_at) || !can(matter.role, "import")}
        >
          <Icon name="upload" size={18} />
          {uiText("Import files")}
        </button>
      </PageHeading>
      <div className="source-intro">
        <span className="source-intro-icon">
          <Icon name="shield" size={27} />
        </span>
        <div>
          <strong>{uiText("Original bytes first. Extraction second.")}</strong>
          <p>
            {uiText(
              "Every original is hashed before processing. Unsupported and partial files remain visible in the import report.",
            )}
          </p>
        </div>
      </div>
      <section className="section">
        <div className="section-heading">
          <h2>
            {uiText("Sources")}{" "}
            <span className="count-chip">
              {number(sources.data?.items.length)}
            </span>
          </h2>
          <button
            className="button secondary compact"
            onClick={() => setSourceModal(true)}
            disabled={!can(matter.role, "import")}
          >
            <Icon name="plus" size={16} />
            {uiText("Add source")}
          </button>
        </div>
        <ErrorBox error={sources.error} retry={sources.refresh} />
        {sources.loading && !sources.data ? (
          <Loading />
        ) : !sources.data?.items.length ? (
          <div className="panel">
            <Empty
              icon="matters"
              title={uiText("No sources registered yet")}
              text={uiText(
                "Add a named source or create one when importing files. Include a custodian to preserve collection context.",
              )}
            />
          </div>
        ) : (
          <div className="source-grid">
            {sources.data.items.map((item) => (
              <div className="source-card" key={item.id}>
                <span className="type-icon">
                  <Icon
                    name={item.kind.includes("email") ? "email" : "matters"}
                  />
                </span>
                <div>
                  <h3>{item.label}</h3>
                  <p>
                    {item.kind === "file-upload"
                      ? uiText("File upload")
                      : item.kind}
                  </p>
                  <small>
                    {item.item_count !== undefined
                      ? uiText("{0} evidence items", {
                          "0": number(item.item_count),
                        })
                      : uiText("Source {0}", { "0": item.id.slice(0, 8) })}
                  </small>
                </div>
                <Badge value="Registered" tone="green" />
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="section">
        <div className="section-heading">
          <h2>{uiText("Import history")}</h2>
          <button
            className="button secondary compact"
            onClick={imports.refresh}
          >
            {uiText("Refresh")}
          </button>
        </div>
        <ErrorBox error={imports.error} retry={imports.refresh} />
        {imports.loading && !imports.data ? (
          <Loading />
        ) : !imports.data?.items.length ? (
          <div className="panel">
            <Empty
              icon="upload"
              title={uiText("Bring the collection together.")}
              text={uiText(
                "Upload one file or a batch. Searchable content appears as the import is processed.",
              )}
            >
              <button
                className="button primary"
                onClick={() => setUpload(true)}
                disabled={!can(matter.role, "import")}
              >
                {uiText("Import evidence")}
              </button>
            </Empty>
          </div>
        ) : (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{uiText("Import batch")}</th>
                  <th>{uiText("Status")}</th>
                  <th>{uiText("Discovered")}</th>
                  <th>{uiText("Indexed")}</th>
                  <th>{uiText("Gaps & errors")}</th>
                  <th>{uiText("Imported")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {imports.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>
                        {item.source_label ||
                          item.filename ||
                          uiText("Import {0}", { "0": item.id.slice(0, 8) })}
                      </strong>
                      <small className="block">{item.id}</small>
                    </td>
                    <td>
                      <Badge value={item.state} />
                    </td>
                    <td>{number(item.counts?.discovered)}</td>
                    <td>{number(item.counts?.indexed)}</td>
                    <td>
                      {number(
                        (item.counts?.failed || 0) +
                          (item.counts?.unsupported || 0) +
                          (item.counts?.partial || 0) +
                          (item.counts?.locked || 0),
                      )}
                    </td>
                    <td>{date(item.created_at)}</td>
                    <td>
                      <button
                        className="button ghost compact"
                        onClick={() => {
                          setActiveBatch(item.id);
                          setActionError(null);
                        }}
                      >
                        {uiText("View report")}
                        <Icon name="arrow" size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {upload && (
        <ImportModal
          matter={matter}
          sources={sources.data?.items || []}
          close={() => setUpload(false)}
          imported={(id) => {
            setUpload(false);
            setActiveBatch(id);
            imports.refresh();
            sources.refresh();
          }}
        />
      )}
      {sourceModal && (
        <SourceModal
          matter={matter}
          close={() => setSourceModal(false)}
          added={() => {
            setSourceModal(false);
            sources.refresh();
          }}
        />
      )}
      {activeBatch && (
        <Modal
          title={uiText("Import report")}
          wide
          close={() => setActiveBatch(null)}
        >
          <ErrorBox error={selected.error} retry={selected.refresh} />
          <ErrorBox error={actionError} />
          {selected.loading && !selected.data ? (
            <Loading />
          ) : (
            selected.data && (
              <>
                <div className="import-report-heading">
                  <span className="mono">{selected.data.id}</span>
                  <Badge value={selected.data.state} />
                </div>
                <div className="import-counts">
                  {Object.entries(selected.data.counts).map(([key, count]) => (
                    <div key={key}>
                      <strong>{number(count)}</strong>
                      <span>{label(key)}</span>
                    </div>
                  ))}
                </div>
                <h3>{uiText("Processing exceptions")}</h3>
                {selected.data.errors?.length ? (
                  <div className="exception-list">
                    {selected.data.errors.map((error, i) => (
                      <div key={`${error.filename}-${i}`}>
                        <Icon name="alert" size={18} />
                        <div>
                          <strong>{error.filename}</strong>
                          <p>{error.message}</p>
                          <small className="mono">{error.code}</small>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    {uiText("No reported processing exceptions.")}
                  </p>
                )}
                <div className="form-actions">
                  {["queued", "pending", "running", "processing"].includes(
                    selected.data.state.toLowerCase(),
                  ) && (
                    <button
                      className="button secondary"
                      disabled={actionBusy}
                      onClick={() => void action("pause")}
                    >
                      {uiText("Pause import")}
                    </button>
                  )}
                  {selected.data.state.toLowerCase() === "paused" && (
                    <button
                      className="button primary"
                      disabled={actionBusy}
                      onClick={() => void action("resume")}
                    >
                      {uiText("Resume import")}
                    </button>
                  )}
                  {Boolean(selected.data.counts.failed) && (
                    <button
                      className="button secondary"
                      disabled={actionBusy}
                      onClick={() => void action("retry")}
                    >
                      {uiText("Retry failed items")}
                    </button>
                  )}
                  <Link
                    className="button primary"
                    href={`/app/matters/${matter.id}/explorer`}
                    onClick={() => setActiveBatch(null)}
                  >
                    {uiText("Explore evidence")}
                    <Icon name="arrow" size={16} />
                  </Link>
                </div>
              </>
            )
          )}
        </Modal>
      )}
      <ImportCapabilities caseId={matter.id} />
    </>
  );
}

function ImportModal({
  matter,
  sources,
  close,
  imported,
}: {
  matter: Matter;
  sources: Source[];
  close: () => void;
  imported: (id: string) => void;
}) {
  const live = useMountedRef();
  const [files, setFiles] = useState<File[]>([]),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [dragging, setDragging] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) return;
    setBusy(true);
    setError(null);
    const data = new FormData(event.currentTarget);
    data.delete("file-picker");
    for (const file of files) data.append("files", file, file.name);
    try {
      const batch = await api<{
        job_id: string;
        batch_id: string;
        state: string;
      }>(`/cases/${matter.id}/imports`, { method: "POST", body: data });
      if (live.current) imported(batch.batch_id || batch.job_id);
    } catch (error) {
      if (live.current) setError(error);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <Modal
      title={uiText("Import evidence")}
      close={() => {
        if (!busy) close();
      }}
      wide
    >
      <form onSubmit={submit}>
        <p className="muted">
          {uiText(
            "Originals are preserved with a SHA-256 hash. Content that cannot be extracted is reported explicitly.",
          )}
        </p>
        <ErrorBox error={error} />
        <label
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            if (busy) return;
            setDragging(false);
            setFiles(Array.from(event.dataTransfer.files));
          }}
        >
          <Icon name="upload" size={30} />
          <strong>
            {files.length
              ? uiText("Files selected: {0}", { "0": number(files.length) })
              : uiText("Drop your evidence here")}
          </strong>
          <span>{uiText("or click to choose files from your computer")}</span>
          <input
            name="file-picker"
            type="file"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files || []))}
            aria-label={uiText("Choose evidence files")}
            disabled={busy}
          />
        </label>
        {files.length > 0 && (
          <div className="file-selection">
            {files.slice(0, 8).map((file, i) => (
              <div key={`${file.name}-${i}`}>
                <Icon name="file" size={16} />
                <span>{file.name}</span>
                <small>{bytes(file.size)}</small>
              </div>
            ))}
            {files.length > 8 && (
              <small>
                {uiText("and {0} more files", {
                  "0": number(files.length - 8),
                })}
              </small>
            )}
          </div>
        )}
        <div className="form-grid">
          <label>
            {uiText("Existing source")}
            <select name="source_id">
              <option value="">
                {uiText("Create a source for this import")}
              </option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            {uiText("New source label")}
            <input
              name="source_label"
              placeholder={uiText("e.g. Finance mailbox collection")}
            />
          </label>
          <label className="full-width">
            {uiText("Custodian name") + " "}
            <span className="optional">{uiText("optional")}</span>
            <input
              name="custodian_name"
              placeholder={uiText(
                "Person or team responsible for this collection",
              )}
            />
          </label>
        </div>
        <div className="notice subtle">
          <Icon name="shield" size={18} />
          <span>
            {uiText(
              "Only import evidence you are authorized to collect. Remote content in email and HTML viewers is blocked.",
            )}
          </span>
        </div>
        <div className="form-actions">
          <button
            className="button secondary"
            type="button"
            onClick={close}
            disabled={busy}
          >
            {uiText("Cancel")}
          </button>
          <button className="button primary" disabled={busy || !files.length}>
            {busy
              ? uiText("Uploading originals…")
              : uiText("Import files: {0}", { "0": number(files.length) })}
            <Icon name="arrow" size={17} />
          </button>
        </div>
      </form>
    </Modal>
  );
}

function SourceModal({
  matter,
  close,
  added,
}: {
  matter: Matter;
  close: () => void;
  added: () => void;
}) {
  const live = useMountedRef();
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <Modal title={uiText("Register a source")} close={close}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await post(
              `/cases/${matter.id}/sources`,
              Object.fromEntries(new FormData(event.currentTarget)),
            );
            if (live.current) added();
          } catch (error) {
            if (live.current) setError(error);
          } finally {
            if (live.current) setBusy(false);
          }
        }}
      >
        <ErrorBox error={error} />
        <label>
          {uiText("Source name")}
          <input
            name="label"
            required
            placeholder={uiText("Executive mailbox")}
          />
        </label>
        <label>
          {uiText("Source type")}
          <select name="kind">
            <option value="file-collection">{uiText("File collection")}</option>
            <option value="email-archive">{uiText("Email archive")}</option>
            <option value="document-collection">
              {uiText("Document collection")}
            </option>
          </select>
        </label>
        <div className="form-actions">
          <button
            className="button primary"
            disabled={busy || !can(matter.role, "import")}
          >
            {busy ? uiText("Saving…") : uiText("Register source")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function PeoplePage({ matter }: { matter: Matter }) {
  const data = useResource<{ items: Person[]; truncated: boolean }>(
      `/cases/${matter.id}/people`,
    ),
    [query, setQuery] = useState("");
  const rows =
    data.data?.items.filter((person) =>
      `${person.name} ${person.email}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    ) || [];
  return (
    <>
      <PageHeading
        eyebrow={uiText("PARTICIPANT DIRECTORY")}
        title={uiText("The people in the record.")}
        text={uiText(
          "Header addresses from imported email. Source occurrences and byte-exact unique originals are counted separately; names never merge distinct addresses.",
        )}
      />
      <div className="section-heading">
        <h2>
          {uiText("Participants")}{" "}
          <span className="count-chip">{number(data.data?.items.length)}</span>
        </h2>
        <label className="search-small">
          <Icon name="search" size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={uiText("Name or email address…")}
            aria-label={uiText("Filter participants")}
          />
        </label>
      </div>
      <ErrorBox error={data.error} retry={data.refresh} />
      {data.loading ? (
        <Loading />
      ) : !rows.length ? (
        <div className="panel">
          <Empty
            icon="people"
            title={uiText("No participants to show")}
            text={uiText(
              "Import emails to build a directory from sender and recipient metadata.",
            )}
          />
        </div>
      ) : (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>{uiText("Participant")}</th>
                <th>{uiText("Sent")}</th>
                <th>{uiText("Received")}</th>
                <th>{uiText("Occurrences")}</th>
                <th>{uiText("Unique originals")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((person) => (
                <tr key={person.id || person.email}>
                  <td>
                    <div className="person-cell">
                      <span className="avatar light">
                        {(person.name || person.email)
                          .slice(0, 2)
                          .toUpperCase()}
                      </span>
                      <div>
                        <strong>{person.name || person.email}</strong>
                        <small className="block">{person.email}</small>
                      </div>
                    </div>
                  </td>
                  <td>{number(person.sent_count)}</td>
                  <td>{number(person.received_count)}</td>
                  <td>
                    <strong>{number(person.total_count)}</strong>
                  </td>
                  <td>
                    {person.unique_messages === undefined
                      ? "—"
                      : number(person.unique_messages)}
                  </td>
                  <td>
                    <Link
                      className="button ghost compact"
                      href={`/app/matters/${matter.id}/explorer?person_id=${encodeURIComponent(person.id)}`}
                    >
                      {uiText("View messages")}
                      <Icon name="arrow" size={15} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.data?.truncated && (
        <div className="notice amber">
          <Icon name="alert" size={17} />
          {uiText(
            "The directory shows the 200 highest-volume header addresses. Use evidence search to inspect other participants.",
          )}
        </div>
      )}
    </>
  );
}

export function TimelinePage({ matter }: { matter: Matter }) {
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const data = useResource<{
    items: TimelineItem[];
    next_cursor?: string | null;
    missing_date_count: number;
    total_items: number;
  }>(
    `/cases/${matter.id}/timeline${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  return (
    <>
      <PageHeading
        eyebrow={uiText("SOURCE CHRONOLOGY")}
        title={uiText("Follow the sequence.")}
        text={uiText(
          "Dates come from evidence metadata. This chronology does not infer events from the document body.",
        )}
      />
      <div className="notice subtle">
        <Icon name="clock" size={18} />
        <span>
          {uiText(
            "Times shown in {0}. Items without a usable date are excluded from this chronology and remain in the evidence explorer.",
            { "0": getDisplayTimeZone() },
          )}
        </span>
      </div>
      {data.data && data.data.missing_date_count > 0 && (
        <div className="notice amber">
          <Icon name="alert" size={17} />
          {number(data.data.missing_date_count)}{" "}
          {" " +
            uiText(
              "preserved evidence items have no usable date and remain available in the evidence explorer.",
            )}
        </div>
      )}
      <ErrorBox error={data.error} retry={data.refresh} />
      {data.loading ? (
        <Loading />
      ) : !data.data?.items.length ? (
        <div className="panel">
          <Empty
            icon="timeline"
            title={uiText("The chronology is waiting for evidence")}
            text={uiText(
              "Dated emails and documents appear here after processing.",
            )}
          />
        </div>
      ) : (
        <div className="timeline-list">
          {data.data.items.map((item) => (
            <Link
              key={item.id || item.evidence_id}
              href={`/app/matters/${matter.id}/evidence/${item.evidence_id}`}
              className="timeline-event"
            >
              <div className="timeline-date">
                <strong>{date(item.date_utc)}</strong>
                <small>
                  {date(item.date_utc, true).split(",").slice(-1).join("")}
                </small>
              </div>
              <span className="timeline-point" />
              <div className="timeline-content">
                <span className="eyebrow">
                  {uiText("{0} · SOURCE METADATA", { "0": label(item.type) })}
                </span>
                <h3>{item.title}</h3>
                <span className="mono">{item.evidence_id}</span>
              </div>
              <Icon name="arrow" size={18} />
            </Link>
          ))}
        </div>
      )}
      <Pagination
        text={
          data.data
            ? uiText("{0} shown of {1} dated evidence items", {
                "0": number(data.data.items.length),
                "1": number(data.data.total_items),
              })
            : undefined
        }
        previous={
          history.length
            ? () => {
                const next = [...history];
                setCursor(next.pop() || null);
                setHistory(next);
              }
            : undefined
        }
        next={
          data.data?.next_cursor
            ? () => {
                setHistory([...history, cursor]);
                setCursor(data.data?.next_cursor || null);
              }
            : undefined
        }
      />
    </>
  );
}

export function AuditPage({ matter }: { matter: Matter }) {
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const data = useResource<{ items: AuditEvent[]; next_cursor: string | null }>(
    `/cases/${matter.id}/audit${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const [verified, setVerified] = useState<{
      valid: boolean;
      events_checked: number;
    } | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <>
      <PageHeading
        eyebrow={uiText("ACCOUNTABLE ACTIONS")}
        title={uiText("A record of the work.")}
        text={uiText(
          "Matter activity attributed to authorized accounts. Hash chaining is an integrity check, not a tamper-proof guarantee.",
        )}
      >
        <button
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              setVerified(await post(`/cases/${matter.id}/audit/verify`));
            } catch (error) {
              setError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Icon name="shield" size={18} />
          {busy ? uiText("Verifying…") : uiText("Verify audit chain")}
        </button>
      </PageHeading>
      <ErrorBox error={error} />
      {verified && (
        <div
          className={`notice ${verified.valid ? "green" : "red"}`}
          role="status"
        >
          <Icon name={verified.valid ? "check" : "alert"} />
          {verified.valid
            ? uiText("Audit chain verified across {0} events.", {
                "0": number(verified.events_checked),
              })
            : uiText(
                "Audit integrity check failed. Investigate before relying on this record.",
              )}
        </div>
      )}
      <ErrorBox error={data.error} retry={data.refresh} />
      {data.loading ? (
        <Loading />
      ) : (
        <div className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>{uiText("Date · {0}", { "0": getDisplayTimeZone() })}</th>
                <th>{uiText("Action")}</th>
                <th>{uiText("Actor")}</th>
                <th>{uiText("Target")}</th>
              </tr>
            </thead>
            <tbody>
              {data.data?.items.map((item) => (
                <tr key={item.id}>
                  <td className="nowrap">
                    {date(item.timestamp || item.created_at, true)}
                  </td>
                  <td>
                    <strong>{label(item.event_type)}</strong>
                  </td>
                  <td className="mono">
                    {item.actor_name || item.actor_id || uiText("System")}
                  </td>
                  <td>
                    <span>
                      {item.target_type
                        ? label(item.target_type)
                        : uiText("Matter")}
                    </span>
                    <small className="block mono">
                      {item.target_id || "—"}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.data?.items.length && (
            <Empty
              icon="shield"
              title={uiText("No audit events")}
              text={uiText("Authorized activity will be recorded here.")}
            />
          )}
        </div>
      )}
      <Pagination
        previous={
          history.length
            ? () => {
                const next = [...history];
                setCursor(next.pop() || null);
                setHistory(next);
              }
            : undefined
        }
        next={
          data.data?.next_cursor
            ? () => {
                setHistory([...history, cursor]);
                setCursor(data.data?.next_cursor || null);
              }
            : undefined
        }
      />
    </>
  );
}

export function ReportsPage({ matter }: { matter: Matter }) {
  const records = useResource<{ items: ExportRecord[] }>(
    `/cases/${matter.id}/exports`,
  );
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const active = records.data?.items.some((item) =>
    ["pending", "queued", "processing", "running"].includes(
      item.state.toLowerCase(),
    ),
  );
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(records.refresh, 2000);
    return () => clearInterval(timer);
  }, [active, records.refresh]);
  const query: SearchSpec = {
    query: "",
    mode: "keyword",
    filters: {},
    sort: [{ field: "evidence_id", order: "asc" }],
    group_by: null,
    page_size: 50,
    cursor: null,
  };
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post(`/cases/${matter.id}/exports`, {
        format: form.get("format"),
        query_spec: query,
        reason: form.get("reason"),
        confirmed: form.get("confirmed") === "on",
      });
      records.refresh();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow={uiText("REVIEWED DELIVERY")}
        title={uiText("Take the record with you.")}
        text={uiText(
          "Permissioned exports with verifiable original hashes and recorded purpose.",
        )}
      />
      <div className="reports-grid">
        <form className="panel export-form" onSubmit={submit}>
          <div className="panel-heading">
            <Icon name="export" size={24} />
            <div>
              <h2>{uiText("Create an evidence export")}</h2>
              <p>
                {uiText(
                  "Exports the full authorized matter. Use the explorer to export a filtered scope.",
                )}
              </p>
            </div>
          </div>
          <ErrorBox error={error} />
          <label>
            {uiText("Export format")}
            <select name="format">
              <option value="csv">
                {uiText("CSV metadata + hash manifest")}
              </option>
              <option value="json">
                {uiText("JSON metadata + hash manifest")}
              </option>
              <option value="zip">
                {uiText("ZIP evidence package + manifest")}
              </option>
            </select>
          </label>
          <label>
            {uiText("Purpose or reason")}
            <textarea
              name="reason"
              required
              minLength={3}
              rows={3}
              placeholder={uiText("Describe the purpose of this export")}
            />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" name="confirmed" required />
            <span>
              {uiText(
                "I have reviewed the scope and am authorized to export this evidence.",
              )}
            </span>
          </label>
          <div className="notice amber">
            <Icon name="lock" size={18} />
            <span>
              {uiText(
                "Privilege, review and integrity holdbacks are enforced by the server. Review decisions may block this export.",
              )}
            </span>
          </div>
          <button className="button primary" disabled={busy}>
            {busy ? uiText("Preparing export…") : uiText("Create export")}
            <Icon name="arrow" size={17} />
          </button>
        </form>
        <div className="panel export-context">
          <span className="eyebrow">{uiText("PRESERVATION FIRST")}</span>
          <h2>{uiText("Keep a connection to the source.")}</h2>
          <p>
            {uiText(
              "A hash manifest lets you verify exported files against the original evidence record. Exported metadata includes stable evidence identifiers and source references.",
            )}
          </p>
          <div>
            <Icon name="shield" />
            <span>
              {uiText("Original files are never stamped or changed.")}
            </span>
          </div>
          <div>
            <Icon name="review" />
            <span>
              {uiText("Human review and privilege decisions remain visible.")}
            </span>
          </div>
          <div>
            <Icon name="clock" />
            <span>
              {uiText("Export actions are attributed in the audit trail.")}
            </span>
          </div>
          <small>
            {uiText(
              "Production redaction and Bates workflows require separate validation before professional use.",
            )}
          </small>
        </div>
      </div>
      <section className="section">
        <div className="section-heading">
          <h2>{uiText("Export history")}</h2>
          <button
            className="button secondary compact"
            onClick={records.refresh}
          >
            {uiText("Refresh")}
          </button>
        </div>
        <ErrorBox error={records.error} retry={records.refresh} />
        {records.loading && !records.data ? (
          <Loading />
        ) : !records.data?.items.length ? (
          <div className="panel">
            <Empty
              icon="export"
              title={uiText("No exports yet")}
              text={uiText(
                "Created export packages appear here after permission and integrity checks.",
              )}
            />
          </div>
        ) : (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{uiText("Export")}</th>
                  <th>{uiText("Format")}</th>
                  <th>{uiText("Status")}</th>
                  <th>{uiText("Created")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {records.data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.id.slice(0, 12)}</td>
                    <td>{item.format.toUpperCase()}</td>
                    <td>
                      <Badge value={item.state} />
                    </td>
                    <td>{date(item.created_at, true)}</td>
                    <td>
                      {["completed", "ready"].includes(
                        item.state.toLowerCase(),
                      ) ? (
                        <div className="tab-actions">
                          <a
                            className="button secondary compact"
                            href={`/api/v1/cases/${matter.id}/exports/${item.id}/download`}
                          >
                            <Icon name="export" size={15} />
                            {uiText("Download")}
                          </a>
                          <a
                            className="button ghost compact"
                            href={`/api/v1/cases/${matter.id}/exports/${item.id}/manifest`}
                          >
                            {uiText("Hash manifest")}
                          </a>
                        </div>
                      ) : (
                        <span className="muted">{label(item.state)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

export function SettingsPage({
  matter,
  refresh,
  user,
  modelPolicy,
}: {
  matter: Matter;
  refresh: () => void;
  user: User;
  modelPolicy: React.ReactNode;
}) {
  const [error, setError] = useState<unknown>(null),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    delete values.matter_number;
    try {
      await api(`/cases/${matter.id}`, {
        method: "PATCH",
        body: JSON.stringify(values),
      });
      refresh();
      setSaved(true);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow={uiText("MATTER CONFIGURATION")}
        title={uiText("Set the boundaries.")}
        text={uiText(
          "Matter details and model availability for this private workspace.",
        )}
      />
      <div className="settings-grid">
        <form className="panel form-panel" onSubmit={submit}>
          <h2>{uiText("Matter details")}</h2>
          <ErrorBox error={error} />
          {saved && (
            <div className="notice green" role="status">
              <Icon name="check" />
              {uiText("Matter details saved.")}
            </div>
          )}
          <label>
            {uiText("Matter number")}
            <input readOnly defaultValue={matter.matter_number} />
          </label>
          <label>
            {uiText("Title")}
            <input name="title" required defaultValue={matter.title} />
          </label>
          <div className="form-grid">
            <label>
              {uiText("Client")}
              <input name="client" defaultValue={matter.client} />
            </label>
            <label>
              {uiText("Jurisdiction")}
              <input name="jurisdiction" defaultValue={matter.jurisdiction} />
            </label>
          </div>
          <label>
            {uiText("Description")}
            <textarea
              name="description"
              rows={4}
              defaultValue={matter.description}
            />
          </label>
          <div className="form-actions">
            <button
              className="button primary"
              disabled={busy || !can(matter.role, "manage")}
            >
              {busy ? uiText("Saving…") : uiText("Save changes")}
            </button>
          </div>
        </form>
        {modelPolicy}
      </div>
      <MatterTeam matter={matter} user={user} />
      <MatterState matter={matter} refresh={refresh} />
    </>
  );
}

function MatterState({
  matter,
  refresh,
}: {
  matter: Matter;
  refresh: () => void;
}) {
  const [modal, setModal] = useState(false),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await post(
        `/cases/${matter.id}/${matter.archived_at ? "restore" : "archive"}`,
        matter.archived_at ? {} : { reason: form.get("reason") },
      );
      setModal(false);
      refresh();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel matter-state-panel">
      <div>
        <h2>{uiText("Matter status")}</h2>
        <p>
          {matter.archived_at
            ? uiText(
                "This matter is archived. Its preserved evidence remains available for authorized viewing.",
              )
            : uiText(
                "Archiving removes this matter from the active list and retains its preserved evidence. It can be restored.",
              )}
        </p>
        <Badge value={matter.archived_at ? "Archived" : "Active"} />
      </div>
      <button
        className="button secondary"
        disabled={!can(matter.role, "manage")}
        onClick={() => setModal(true)}
      >
        <Icon name={matter.archived_at ? "back" : "matters"} size={17} />
        {matter.archived_at
          ? uiText("Restore matter")
          : uiText("Archive matter")}
      </button>
      {modal && (
        <Modal
          title={
            matter.archived_at
              ? uiText("Restore this matter")
              : uiText("Archive this matter")
          }
          close={() => setModal(false)}
        >
          <form onSubmit={submit}>
            <ErrorBox error={error} />
            <p className="muted">
              {matter.archived_at
                ? uiText(
                    "Restore this matter to the active workspace. This action is recorded in the audit trail.",
                  )
                : uiText(
                    "Original evidence is retained. An active preservation hold prevents archival and will be checked by the server.",
                  )}
            </p>
            {!matter.archived_at && (
              <label>
                {uiText("Archive reason")}
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={3}
                />
              </label>
            )}
            <label className="checkbox-label">
              <input type="checkbox" required />
              <span>
                {uiText("I am authorized to {0} this matter.", {
                  "0": matter.archived_at
                    ? uiText("restore")
                    : uiText("archive"),
                })}
              </span>
            </label>
            <div className="form-actions">
              <button className="button primary" disabled={busy}>
                {busy
                  ? uiText("Updating matter…")
                  : matter.archived_at
                    ? uiText("Restore matter")
                    : uiText("Archive matter")}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export function Pagination({
  previous,
  next,
  text,
}: {
  previous?: () => void;
  next?: () => void;
  text?: string;
}) {
  return (
    <div className="pagination">
      <span>{text}</span>
      <div>
        <button
          className="button secondary compact"
          disabled={!previous}
          onClick={previous}
        >
          <Icon name="back" size={15} />
          {uiText("Previous")}
        </button>
        <button
          className="button secondary compact"
          disabled={!next}
          onClick={next}
        >
          {uiText("Next")}
          <Icon name="arrow" size={15} />
        </button>
      </div>
    </div>
  );
}
