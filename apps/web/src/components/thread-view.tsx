"use client";

import { useState } from "react";
import { date, number } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Evidence } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading } from "./ui";
import { Pagination } from "./matter-pages";

export default function ThreadView({
  caseId,
  id,
  open,
}: {
  caseId: string;
  id: string;
  open: (id: string) => void;
}) {
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const resource = useResource<{
    items: Evidence[];
    total_hits: number;
    next_cursor: string | null;
    warnings: string[];
  }>(
    `/cases/${caseId}/emails/${id}/thread${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  return (
    <>
      <ErrorBox error={resource.error} retry={resource.refresh} />
      {resource.loading ? (
        <Loading text="Opening collected conversation…" />
      ) : (
        resource.data && (
          <>
            <div className="thread-scope">
              <span className="eyebrow">EXPLICIT HEADER LINKS</span>
              <strong>
                {number(resource.data.total_hits)} collected{" "}
                {resource.data.total_hits === 1 ? "message" : "messages"}
              </strong>
              <p>
                Only explicit message identifiers connect these records.
                Collection completeness has not been assessed.
              </p>
            </div>
            <div className="thread-messages">
              {resource.data.items.map((item) => (
                <button
                  key={item.evidence_id}
                  onClick={() => open(item.evidence_id)}
                  className={item.evidence_id === id ? "current" : ""}
                >
                  <span className="thread-message-dot" />
                  <div>
                    <small>{date(item.date_utc, true)}</small>
                    <strong>{item.title}</strong>
                    <span>{item.sender}</span>
                    <p>{item.snippet}</p>
                    <Badge value={item.review_status} />
                  </div>
                  <Icon name="chevron" size={14} />
                </button>
              ))}
            </div>
            <Pagination
              previous={
                history.length
                  ? () => {
                      const pages = [...history];
                      setCursor(pages.pop() || null);
                      setHistory(pages);
                    }
                  : undefined
              }
              next={
                resource.data.next_cursor
                  ? () => {
                      setHistory([...history, cursor]);
                      setCursor(resource.data!.next_cursor);
                    }
                  : undefined
              }
            />
            {resource.data.warnings?.map((warning, i) => (
              <p className="field-help" key={i}>
                {warning}
              </p>
            ))}
          </>
        )
      )}
    </>
  );
}
