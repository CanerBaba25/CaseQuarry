"use client";
import { uiText } from "@/lib/i18n";

import { useResource } from "@/lib/hooks";
import { uiLabel as label } from "@/lib/api";
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
          <strong>{uiText("Import capabilities on this installation")}</strong>
        </span>
        <Icon name="chevron" size={16} />
      </summary>
      <p className="muted">
        {uiText(
          "Format readiness reflects the installed parsers and optional local tools. Unsupported and partial records remain preserved and visible in import reports.",
        )}
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
                  <th>{uiText("Formats")}</th>
                  <th>{uiText("Readiness")}</th>
                  <th>{uiText("Engine")}</th>
                  <th>{uiText("Handling and limits")}</th>
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
                    <td>{adapter.engine || uiText("Not configured")}</td>
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
          <h3>{uiText("Authorized collection connectors")}</h3>
          <div className="connector-list">
            {resource.data?.connectors.map((connector) => (
              <div key={connector.id}>
                <strong>{label(connector.id)}</strong>
                <Badge value={connector.status} />
                <p>
                  {connector.read_only
                    ? uiText("Read-only collection")
                    : uiText("Collection")}{" "}
                  · {connector.mode.toUpperCase()} ·{" "}
                  {connector.requires_explicit_scope
                    ? uiText("Explicit authorized scope required")
                    : uiText("See collection policy")}
                </p>
              </div>
            ))}
          </div>
          <p className="field-help">
            {uiText(
              "These acquisition connectors run through the local command line. Web uploads use the preserved files you explicitly select; no mailbox connection or external consent is initiated here.",
            )}
          </p>
        </>
      )}
    </details>
  );
}
