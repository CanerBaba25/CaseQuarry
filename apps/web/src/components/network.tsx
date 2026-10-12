"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { number } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Matter } from "@/lib/types";
import { Empty, ErrorBox, Icon, Loading } from "./ui";
import { PageHeading, Pagination } from "./matter-pages";
import {
  CommunicationScopeForm,
  scopeFilters,
  scopeParams,
  type CommunicationScope,
} from "./communication-analytics";
import { evidenceUrl } from "@/lib/search-scope";

type Node = { id: string; email: string; name: string; state: string };
type Edge = {
  source: string;
  target: string;
  count: number;
  unique_messages: number;
  unique_threads: number;
};
type Network = {
  nodes: Node[];
  edges: Edge[];
  truncated: boolean;
  count_basis: string;
};

export default function NetworkPage({ matter }: { matter: Matter }) {
  const [scope, setScope] = useState<CommunicationScope>({});
  const resource = useResource<Network>(
      `/cases/${matter.id}/network?${scopeParams(scope)}`,
    ),
    [page, setPage] = useState(0);
  const nodes = new Map(
    resource.data?.nodes.map((node) => [node.id, node]) || [],
  );
  const edges = resource.data?.edges || [],
    visible = edges.slice(page * 50, (page + 1) * 50);
  return (
    <>
      <PageHeading
        eyebrow="COLLECTED COMMUNICATIONS"
        title="See the connections."
        text="Directed sender-to-recipient relationships from email headers. Addresses are not automatically merged into human identities."
      />
      <CommunicationScopeForm
        matter={matter}
        apply={(value) => {
          setScope(value);
          setPage(0);
        }}
      />
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading ? (
        <Loading />
      ) : !edges.length ? (
        <div className="panel">
          <Empty
            icon="network"
            title="Connections appear with correspondence"
            text="Import emails with sender and recipient headers to build a source-backed communication map."
          />
        </div>
      ) : (
        <>
          <div className="notice subtle">
            <Icon name="people" size={18} />
            <span>
              Counts include every preserved source occurrence. Unique originals
              count byte-exact original messages separately.
              {resource.data?.truncated
                ? " This view is limited to the 500 highest-volume address pairs."
                : ""}
            </span>
          </div>
          <section className="panel network-map-panel">
            <div className="section-heading">
              <div>
                <h2>Communication map</h2>
                <p className="muted">
                  Up to 20 connected header addresses from the returned pairs.
                  Open an address to inspect its exact message scope.
                </p>
              </div>
              <span className="count-chip">
                {number(resource.data?.nodes.length)} returned addresses
              </span>
            </div>
            <CommunicationMap
              matter={matter}
              data={resource.data!}
              scope={scope}
            />
          </section>
          <section className="section">
            <div className="section-heading">
              <h2>Communication pairs</h2>
              <span className="muted">
                {number(edges.length)} returned pairs
              </span>
            </div>
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Sender → Recipient</th>
                    <th>Occurrences</th>
                    <th>Unique originals</th>
                    <th>Explicit threads</th>
                    <th>
                      <span className="sr-only">Directed evidence scope</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((edge) => (
                    <tr key={`${edge.source}-${edge.target}`}>
                      <td>
                        <div className="communication-pair">
                          <Link
                            href={evidenceUrl(
                              matter.id,
                              {
                                ...scopeFilters(scope),
                                person_id: edge.source,
                              },
                              true,
                            )}
                          >
                            {nodes.get(edge.source)?.email || edge.source}
                          </Link>
                          <Icon name="arrow" size={14} />
                          <Link
                            href={evidenceUrl(
                              matter.id,
                              {
                                ...scopeFilters(scope),
                                person_id: edge.target,
                              },
                              true,
                            )}
                          >
                            {nodes.get(edge.target)?.email || edge.target}
                          </Link>
                        </div>
                      </td>
                      <td>
                        <strong>{number(edge.count)}</strong>
                      </td>
                      <td>{number(edge.unique_messages)}</td>
                      <td>{number(edge.unique_threads)}</td>
                      <td>
                        <Link
                          className="text-link"
                          href={evidenceUrl(
                            matter.id,
                            {
                              ...scopeFilters(scope),
                              sender_person_id: edge.source,
                              recipient_person_id: edge.target,
                            },
                            true,
                          )}
                        >
                          Open pair <Icon name="arrow" size={14} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              text={`Pairs ${page * 50 + 1}–${Math.min((page + 1) * 50, edges.length)} of ${number(edges.length)} returned`}
              previous={page ? () => setPage((value) => value - 1) : undefined}
              next={
                (page + 1) * 50 < edges.length
                  ? () => setPage((value) => value + 1)
                  : undefined
              }
            />
          </section>
        </>
      )}
    </>
  );
}

function CommunicationMap({
  matter,
  data,
  scope,
}: {
  matter: Matter;
  data: Network;
  scope: CommunicationScope;
}) {
  const chart = useMemo(() => {
    const weights = new Map<string, number>();
    for (const edge of data.edges)
      for (const key of [edge.source, edge.target])
        weights.set(key, (weights.get(key) || 0) + edge.count);
    const chosen = [...data.nodes]
      .sort(
        (a, b) =>
          (weights.get(b.id) || 0) - (weights.get(a.id) || 0) ||
          a.id.localeCompare(b.id),
      )
      .slice(0, 20);
    const maximum = Math.max(
      ...chosen.map((node) => weights.get(node.id) || 0),
      1,
    );
    const nodes = chosen.map((node, i) => {
      const angle =
        ((i - 1) / Math.max(1, chosen.length - 1)) * Math.PI * 2 - Math.PI / 2;
      return {
        ...node,
        x: i === 0 ? 450 : 450 + Math.cos(angle) * 295,
        y: i === 0 ? 245 : 245 + Math.sin(angle) * 160,
        radius: 13 + ((weights.get(node.id) || 0) / maximum) * 16,
      };
    });
    const ids = new Map(nodes.map((node) => [node.id, node]));
    return {
      nodes,
      edges: data.edges
        .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
        .map((edge) => ({
          ...edge,
          start: ids.get(edge.source)!,
          end: ids.get(edge.target)!,
        })),
    };
  }, [data]);
  return (
    <svg
      className="communication-map"
      viewBox="0 0 900 500"
      role="img"
      aria-labelledby="network-title network-description"
    >
      <title id="network-title">
        Collected sender-to-recipient communication map
      </title>
      <desc id="network-description">
        A bounded visualization of up to 20 header addresses. The communication
        pair table provides exact returned occurrence and unique original
        counts.
      </desc>
      <defs>
        <marker
          id="arrowhead"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M0 0L6 3L0 6Z" fill="var(--muted)" />
        </marker>
      </defs>
      {chart.edges.map((edge) => (
        <line
          key={`${edge.source}-${edge.target}`}
          x1={edge.start.x}
          y1={edge.start.y}
          x2={
            edge.end.x -
            ((edge.end.x - edge.start.x) /
              Math.max(
                1,
                Math.hypot(
                  edge.end.x - edge.start.x,
                  edge.end.y - edge.start.y,
                ),
              )) *
              (edge.end.radius + 4)
          }
          y2={
            edge.end.y -
            ((edge.end.y - edge.start.y) /
              Math.max(
                1,
                Math.hypot(
                  edge.end.x - edge.start.x,
                  edge.end.y - edge.start.y,
                ),
              )) *
              (edge.end.radius + 4)
          }
          stroke="var(--muted)"
          strokeOpacity="0.22"
          strokeWidth={Math.min(4, 1 + Math.log1p(edge.count) * 0.35)}
          markerEnd="url(#arrowhead)"
        >
          <title>
            {edge.count} preserved occurrences · {edge.unique_messages} unique
            originals
          </title>
        </line>
      ))}
      {chart.nodes.map((node, i) => (
        <a
          key={node.id}
          href={evidenceUrl(
            matter.id,
            { ...scopeFilters(scope), person_id: node.id },
            true,
          )}
          aria-label={`Open exact messages for ${node.email}`}
        >
          <circle
            cx={node.x}
            cy={node.y}
            r={node.radius}
            fill={i === 0 ? "var(--accent)" : "var(--accent-light)"}
            stroke="var(--accent)"
            strokeWidth="1.2"
          />
          <text
            x={node.x}
            y={node.y + 4}
            textAnchor="middle"
            fontSize="11"
            fill={i === 0 ? "var(--surface)" : "var(--accent)"}
          >
            {(node.name || node.email).slice(0, 2).toUpperCase()}
          </text>
          <text
            x={node.x}
            y={node.y + node.radius + 19}
            textAnchor="middle"
            fontSize="10"
            fill="var(--ink)"
          >
            {node.name
              ? node.name.slice(0, 26)
              : node.email.split("@")[0].slice(0, 26)}
          </text>
          <text
            x={node.x}
            y={node.y + node.radius + 34}
            textAnchor="middle"
            fontSize="8"
            fill="var(--muted)"
          >
            {node.email.slice(0, 38)}
          </text>
          <title>{node.email} · header address</title>
        </a>
      ))}
    </svg>
  );
}
