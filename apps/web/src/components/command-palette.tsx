"use client";
import { uiText, type MessageKey } from "@/lib/i18n";

import { useEffect, useId, useRef, useState } from "react";
import { number } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Matter } from "@/lib/types";
import { Badge, ErrorBox, Icon, Loading, Modal } from "./ui";

type Action = {
  title: string;
  path: string;
  icon: string;
  detail?: string;
  archived?: boolean;
};
type MatterPage = {
  items: Matter[];
  next_cursor: string | null;
  total: number;
};

export default function CommandPalette({
  caseId,
  navigation,
  administrator,
  close,
  navigate,
}: {
  caseId: string | null;
  navigation: [string, MessageKey, string][];
  administrator: boolean;
  close: () => void;
  navigate: (path: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [selected, setSelected] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query.trim());
      setCursors([null]);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    input.current?.focus();
  }, []);
  const cursor = cursors.at(-1);
  const matters = useResource<MatterPage>(
    `/cases?limit=12&archived=${archived}&q=${encodeURIComponent(search)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const searching = query.trim() !== search || matters.loading;
  const pages: Action[] = [
    {
      title: uiText("All matters"),
      path: "/app",
      icon: "matters",
      detail: uiText("Firm workspace"),
    },
    {
      title: uiText("Create a matter"),
      path: "/app/matters/new",
      icon: "plus",
      detail: uiText("Start an investigation"),
    },
    {
      title: uiText("Account security"),
      path: "/app/settings",
      icon: "shield",
      detail: uiText("Sessions, password and connections"),
    },
    ...(administrator
      ? [
          {
            title: uiText("Firm administration"),
            path: "/app/admin",
            icon: "people",
            detail: uiText("Manage firm accounts and policy"),
          },
        ]
      : []),
    ...(caseId
      ? navigation.map(([key, title, icon]) => ({
          title: uiText(title),
          path: `/app/matters/${caseId}/${key}`,
          icon,
          detail: uiText("Current matter"),
        }))
      : []),
  ].filter((item) =>
    item.title.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const found: Action[] =
    searching || matters.error
      ? []
      : (matters.data?.items ?? []).map((matter) => ({
          title: matter.title,
          detail: `${matter.matter_number}${matter.client ? ` · ${matter.client}` : ""}`,
          path: `/app/matters/${matter.id}/overview`,
          icon: "matters",
          archived: Boolean(matter.archived_at),
        }));
  const options = [...pages, ...found];
  useEffect(() => {
    setSelected(0);
  }, [query, search, archived, cursor, matters.data]);
  useEffect(() => {
    document
      .getElementById(`${id}-option-${selected}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [id, selected, search, cursor, archived, matters.data]);
  const active = options.length ? Math.min(selected, options.length - 1) : -1;

  function option(item: Action, index: number) {
    return (
      <button
        key={item.path}
        id={`${id}-option-${index}`}
        type="button"
        role="option"
        aria-selected={active === index}
        className={active === index ? "selected" : ""}
        onPointerMove={() => setSelected(index)}
        onClick={() => navigate(item.path)}
      >
        <span className="palette-option-icon">
          <Icon name={item.icon} size={19} />
        </span>
        <span className="palette-option-text">
          <strong>{item.title}</strong>
          <small>{item.detail}</small>
        </span>
        {item.archived && <Badge value="Archived" />}
        <Icon name="arrow" size={15} />
      </button>
    );
  }
  return (
    <Modal title={uiText("Quick navigation")} close={close}>
      <div className="command-palette">
        <label className="palette-search">
          <Icon name="search" />
          <input
            ref={input}
            value={query}
            maxLength={200}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={uiText("Search matter title, number, client or page…")}
            aria-label={uiText("Search navigation")}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="true"
            aria-controls={`${id}-results`}
            aria-activedescendant={
              active >= 0 ? `${id}-option-${active}` : undefined
            }
            onKeyDown={(event) => {
              if (
                ["ArrowDown", "ArrowUp"].includes(event.key) &&
                options.length
              ) {
                event.preventDefault();
                setSelected(
                  (current) =>
                    (current +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      options.length) %
                    options.length,
                );
              } else if (event.key === "Enter" && active >= 0) {
                event.preventDefault();
                navigate(options[active].path);
              }
            }}
          />
        </label>
        <div className="palette-scope">
          <span>
            <Icon name="lock" size={13} />{" "}
            {" " + uiText("Only matters you can access")}
          </span>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={archived}
              onChange={(event) => {
                setArchived(event.target.checked);
                setCursors([null]);
              }}
            />{" "}
            {uiText("Include archived matters")}
          </label>
        </div>
        <div
          className="palette-results"
          id={`${id}-results`}
          role="listbox"
          aria-label={uiText("Navigation results")}
          aria-busy={searching}
        >
          {Boolean(pages.length) && (
            <div className="palette-group-label" role="presentation">
              {uiText("Pages & commands")}
            </div>
          )}
          {pages.map(option)}
          <div className="palette-group-label" role="presentation">
            {uiText("Matters")}{" "}
            <span>
              {!searching && matters.data ? number(matters.data.total) : ""}
            </span>
          </div>
          {found.map((item, index) => option(item, pages.length + index))}
          {searching && (
            <Loading text={uiText("Searching authorized matters…")} />
          )}
          {!searching && !matters.error && !found.length && (
            <p className="palette-empty">
              {uiText(
                "No matching matters. Try a title, client or matter number.",
              )}
            </p>
          )}
        </div>
        <ErrorBox error={matters.error} retry={matters.refresh} />
        {(cursors.length > 1 || matters.data?.next_cursor) && (
          <div className="palette-pagination">
            <button
              type="button"
              className="button secondary compact"
              disabled={cursors.length === 1 || searching}
              onClick={() => setCursors((current) => current.slice(0, -1))}
            >
              {uiText("Previous matters")}
            </button>
            <span>{uiText("{0} on this page", { "0": found.length })}</span>
            <button
              type="button"
              className="button secondary compact"
              disabled={!matters.data?.next_cursor || searching}
              onClick={() => {
                if (matters.data?.next_cursor)
                  setCursors((current) => [
                    ...current,
                    matters.data!.next_cursor,
                  ]);
              }}
            >
              {uiText("Next matters")}
            </button>
          </div>
        )}
        <div className="palette-keyboard">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> {" " + uiText("Navigate")}
          </span>
          <span>
            <kbd>Enter</kbd> {" " + uiText("Open")}
          </span>
          <span>
            <kbd>Esc</kbd> {" " + uiText("Close")}
          </span>
        </div>
      </div>
    </Modal>
  );
}
