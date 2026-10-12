"use client";

import { useResource } from "@/lib/hooks";
import { label } from "@/lib/api";
import { Badge, ErrorBox, Icon, Loading } from "./ui";

type Adapter = {
  id: string;
  formats: string[];
  status: string;
  engine: string | null;
  detail: string;
  limits: Record<string, unknown> | string;
};
export default function ImportCapabilities({ caseId }: { caseId: string }) {
  const resource = useResource<{
    items: Adapter[];
    connectors: {
      id: string;
      mode: string;
      read_only: boolean;
      requires_explicit_scope: boolean;
      status: string;
    }[];
  }>(`/cases/${caseId}/imports/adapters`);
  return (
    <details className="panel capabilities-panel">
      <summary>
        <span>
          <Icon name="file" size={19} />
          <strong>Import capabilities on this installation</strong>
        </span>
        <Icon name="chevron" size={16} />
      </summary>
      <p className="muted">
        Format readiness reflects the installed parsers and optional local
        tools. Unsupported and partial records remain preserved and visible in
        import reports.
      </p>
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading ? (
        <Loading />
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Formats</th>
                  <th>Readiness</th>
                  <th>Engine</th>
                  <th>Handling and limits</th>
                </tr>
              </thead>
              <tbody>
                {resource.data?.items.map((adapter) => (
                  <tr key={adapter.id}>
                    <td>
                      <strong>
                        {adapter.formats.join(", ") || label(adapter.id)}
                      </strong>
                    </td>
                    <td>
                      <Badge
                        value={adapter.status}
                        tone={
                          adapter.status === "available" ? "green" : "amber"
                        }
                      />
                    </td>
                    <td>{adapter.engine || "Not configured"}</td>
                    <td>
                      {adapter.detail}
                      {adapter.limits && (
                        <small className="block">
                          {typeof adapter.limits === "string"
                            ? adapter.limits
                            : Object.entries(adapter.limits)
                                .map(
                                  ([key, value]) =>
                                    `${label(key)}: ${String(value)}`,
                                )
                                .join(" · ")}
                        </small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Authorized collection connectors</h3>
          <div className="connector-list">
            {resource.data?.connectors.map((connector) => (
              <div key={connector.id}>
                <strong>{label(connector.id)}</strong>
                <Badge value={connector.status} />
                <p>
                  {connector.read_only ? "Read-only collection" : "Collection"}{" "}
                  · {connector.mode.toUpperCase()} ·{" "}
                  {connector.requires_explicit_scope
                    ? "Explicit authorized scope required"
                    : "See collection policy"}
                </p>
              </div>
            ))}
          </div>
          <p className="field-help">
            These acquisition connectors run through the local command line. Web
            uploads use the preserved files you explicitly select; no mailbox
            connection or external consent is initiated here.
          </p>
        </>
      )}
    </details>
  );
}
