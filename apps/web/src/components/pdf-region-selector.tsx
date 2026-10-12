"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorBox, Icon, Loading } from "./ui";

type Region = {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
};
type Point = { x: number; y: number };

export default function PdfRegionSelector({
  caseId,
  evidenceId,
  originalHash,
  regions,
  change,
}: {
  caseId: string;
  evidenceId: string;
  originalHash: string;
  regions: Region[];
  change: (regions: Region[]) => void;
}) {
  const [page, setPage] = useState(1),
    [preview, setPreview] = useState<{
      key: string;
      url: string;
      pages: number;
    } | null>(null),
    [error, setError] = useState<unknown>(null),
    [anchor, setAnchor] = useState<Point | null>(null),
    [pointer, setPointer] = useState<Point | null>(null);
  const image = useRef<HTMLImageElement>(null),
    key = `${caseId}:${evidenceId}:${page}:${originalHash}`;
  const current = preview?.key === key ? preview : null;
  useEffect(() => {
    const controller = new AbortController();
    let url: string | null = null;
    setError(null);
    setAnchor(null);
    setPointer(null);
    fetch(
      `/api/v1/cases/${caseId}/evidence/${evidenceId}/page-preview?page=${page}`,
      {
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      },
    )
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401)
            window.dispatchEvent(new Event("cq:unauthorized"));
          const result = await response.json().catch(() => ({}));
          throw new Error(
            result.message || "The source page preview is unavailable.",
          );
        }
        if (
          response.headers.get("X-Original-SHA256") !== originalHash ||
          !response.headers.get("Content-Type")?.startsWith("image/png")
        )
          throw new Error(
            "Source verification changed. Reload the evidence before selecting page regions.",
          );
        const pages = Number(response.headers.get("X-Page-Count"));
        if (!Number.isInteger(pages) || pages < 1 || pages > 50)
          throw new Error(
            "The preview page count is unavailable or exceeds the supported limit.",
          );
        const data = await response.arrayBuffer();
        const expected = response.headers.get("X-Content-SHA256");
        if (expected && globalThis.crypto?.subtle) {
          const digest = Array.from(
            new Uint8Array(await crypto.subtle.digest("SHA-256", data)),
            (byte) => byte.toString(16).padStart(2, "0"),
          ).join("");
          if (digest !== expected)
            throw new Error("The page preview failed its integrity check.");
        }
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(new Blob([data], { type: "image/png" }));
        setPreview({ key, url, pages });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [caseId, evidenceId, page, originalHash, key]);
  function position(event: React.PointerEvent): Point {
    const rect = image.current!.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  }
  const selection =
    anchor && pointer
      ? {
          page,
          x: Math.min(anchor.x, pointer.x),
          y: Math.min(anchor.y, pointer.y),
          width: Math.abs(pointer.x - anchor.x),
          height: Math.abs(pointer.y - anchor.y),
        }
      : null;
  return (
    <section className="pdf-region-selector">
      <div className="section-heading">
        <div>
          <h3>Verified source-page preview</h3>
          <p className="field-help">
            Drag a rectangle over this raster page, or enter exact normalized
            coordinates below. Original PDF objects and scripts are not
            embedded.
          </p>
        </div>
        <label className="inline-select">
          Page
          <input
            type="number"
            aria-label="PDF preview page"
            min={1}
            max={current?.pages || 50}
            value={page}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (
                Number.isInteger(value) &&
                value >= 1 &&
                value <= (current?.pages || 50)
              )
                setPage(value);
            }}
          />
          <span>of {current?.pages || "—"}</span>
        </label>
      </div>
      <ErrorBox error={error} />
      {!current && !error ? (
        <Loading text="Rendering and verifying source page…" />
      ) : (
        current && (
          <div
            className="pdf-region-surface"
            aria-label="PDF region selection surface"
            onPointerDown={(event) => {
              if (!image.current || regions.length >= 200 || event.button !== 0)
                return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              const point = position(event);
              setAnchor(point);
              setPointer(point);
            }}
            onPointerMove={(event) => {
              if (anchor && image.current) setPointer(position(event));
            }}
            onPointerUp={(event) => {
              if (!anchor || !image.current) return;
              const end = position(event);
              const region = {
                page,
                x: Math.min(anchor.x, end.x),
                y: Math.min(anchor.y, end.y),
                width: Math.abs(end.x - anchor.x),
                height: Math.abs(end.y - anchor.y),
              };
              if (region.width > 0.001 && region.height > 0.001)
                change([...regions, region]);
              setAnchor(null);
              setPointer(null);
            }}
            onPointerCancel={() => {
              setAnchor(null);
              setPointer(null);
            }}
          >
            <img
              ref={image}
              src={current.url}
              alt={`Verified raster of source PDF page ${page}; use the coordinate form to create redactions with a keyboard.`}
              draggable={false}
            />
            {[
              ...regions.filter((region) => region.page === page),
              ...(selection ? [selection] : []),
            ].map((region, index) => (
              <span
                key={index}
                className={`pdf-region-overlay ${index >= regions.filter((region) => region.page === page).length ? "draft" : ""}`}
                style={{
                  left: `${region.x * 100}%`,
                  top: `${region.y * 100}%`,
                  width: `${region.width * 100}%`,
                  height: `${region.height * 100}%`,
                }}
              />
            ))}
          </div>
        )
      )}
      <p className="field-help">
        <Icon name="lock" size={13} /> Coordinates use the exact source page
        shown above. Generated sanitized copies still require a distinct human
        approval.
      </p>
    </section>
  );
}
