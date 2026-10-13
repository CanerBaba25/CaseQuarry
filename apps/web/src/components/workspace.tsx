"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  date,
  getDisplayTimeZone,
  number,
  post,
  setDisplayTimeZone,
  timeZoneSupported,
} from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { useFirmSync } from "@/lib/sync";
import type { Matter, Stats, User } from "@/lib/types";
import { Badge, Empty, ErrorBox, Icon, Loading, Logo } from "./ui";
import CommandPalette from "./command-palette";
import TimeZoneSettings from "./time-zone-settings";
import {
  MatterOverview,
  SourcesPage,
  PeoplePage,
  TimelinePage,
  AuditPage,
  ReportsPage,
  SettingsPage,
} from "./matter-pages";
import Explorer from "./explorer";
import { GovernancePage } from "./governance";
import AccountSecurity from "./account-security";
import NetworkPage from "./network";
import SourceAssistant, { LocalModelPolicy } from "./local-model";
import CommunicationAnalytics from "./communication-analytics";
import FirmAdministration from "./firm-admin";
import ReviewQueue from "./review-queue";
import ProductionsPage from "./productions";
import MyWork from "./task-worklist";

type MatterPage = {
  items: Matter[];
  next_cursor: string | null;
  total: number;
};

const matterNavigation = [
  ["overview", "Overview", "grid"],
  ["explorer", "Evidence explorer", "search"],
  ["emails", "Email workspace", "email"],
  ["sources", "Sources & imports", "upload"],
  ["people", "People", "people"],
  ["network", "Communication map", "network"],
  ["analytics", "Traffic analytics", "timeline"],
  ["timeline", "Timeline", "timeline"],
  ["review", "Review queue", "review"],
  ["ai", "Source assistant", "sparkle"],
  ["issues", "Issue matrix", "matters"],
  ["tasks", "Tasks", "review"],
  ["holds", "Preservation holds", "lock"],
  ["reports", "Exports", "export"],
  ["productions", "Productions", "export"],
  ["audit", "Audit trail", "shield"],
  ["settings", "Matter settings", "settings"],
];
const matterGroups = [
  { title: "Evidence", keys: ["overview", "explorer", "emails", "sources"] },
  {
    title: "Investigation",
    keys: ["people", "network", "analytics", "timeline"],
  },
  { title: "Review & work", keys: ["review", "issues", "tasks", "ai"] },
  {
    title: "Delivery & control",
    keys: ["productions", "reports", "holds", "audit", "settings"],
  },
];

export default function Workspace() {
  const router = useRouter(),
    pathname = usePathname();
  const [user, setUser] = useState<User | null>(null),
    [booting, setBooting] = useState(true),
    [setup, setSetup] = useState(false),
    [bootError, setBootError] = useState<unknown>(null);
  const [palette, setPalette] = useState(false),
    [navOpen, setNavOpen] = useState(false),
    [dark, setDark] = useState(false);
  const [commandKey, setCommandKey] = useState("Ctrl");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [matterFilter, setMatterFilter] = useState("");
  const [caseSearch, setCaseSearch] = useState("");
  const [caseCursors, setCaseCursors] = useState<(string | null)[]>([null]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setCaseSearch(matterFilter.trim());
      setCaseCursors([null]);
    }, 250);
    return () => clearTimeout(timer);
  }, [matterFilter]);
  useEffect(() => {
    setCaseCursors([null]);
  }, [includeArchived, user?.id]);
  const pieces = pathname.split("/").filter(Boolean),
    caseId =
      pieces[0] === "app" && pieces[1] === "matters" && pieces[2] !== "new"
        ? pieces[2]
        : null;
  const section = pieces[3] || "overview";
  const accountSettings = pieces[0] === "app" && pieces[1] === "settings";
  const administration = pieces[0] === "app" && pieces[1] === "admin";
  const navigationRef = useRef<HTMLElement>(null),
    menuRef = useRef<HTMLButtonElement>(null);
  const matter = useResource<Matter>(
    user && caseId ? `/cases/${caseId}` : null,
  );
  const cases = useResource<MatterPage>(
    user
      ? `/cases?limit=24&archived=${includeArchived}&q=${encodeURIComponent(caseSearch)}${caseCursors.at(-1) ? `&cursor=${encodeURIComponent(caseCursors.at(-1)!)}` : ""}`
      : null,
  );
  const refreshUser = useCallback(() => {
    void api<User>("/me")
      .then((me) => {
        setUser((current) =>
          current?.id === me.id && current.tenant_id === me.tenant_id
            ? me
            : current,
        );
      })
      .catch(() => {});
  }, []);
  const syncState = useFirmSync(user?.id ?? null, caseId, refreshUser);
  const timeZoneIdentity = useRef<{ userId: string; zone: string } | null>(
    null,
  );
  useEffect(() => {
    const zone = user?.time_zone || "UTC";
    const previous = timeZoneIdentity.current;
    setDisplayTimeZone(zone);
    timeZoneIdentity.current = user ? { userId: user.id, zone } : null;
    if (user && previous?.userId === user.id && previous.zone !== zone) {
      window.dispatchEvent(
        new CustomEvent("cq:refresh", { detail: { system: true } }),
      );
    }
  }, [user?.id, user?.time_zone]);

  const boot = useCallback(async () => {
    setBooting(true);
    setBootError(null);
    try {
      const state = await api<{ required: boolean }>("/setup");
      setSetup(state.required);
      if (state.required) {
        if (window.location.pathname !== "/setup") router.replace("/setup");
        return;
      }
      try {
        const me = await api<User>("/me");
        setUser(me);
        if (!window.location.pathname.startsWith("/app"))
          router.replace("/app");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
          if (window.location.pathname !== "/login") router.replace("/login");
        } else throw error;
      }
    } catch (error) {
      setBootError(error);
    } finally {
      setBooting(false);
    }
  }, [router]);
  useEffect(() => {
    void boot();
  }, [boot]);
  useEffect(() => {
    let theme: string | null = null;
    try {
      theme = window.localStorage.getItem("cq_theme");
    } catch {}
    setCommandKey(/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl");
    setDark(theme === "dark");
    document.documentElement.dataset.theme =
      theme === "dark" ? "dark" : "light";
    const unauthorized = () => {
      setUser(null);
      if (window.location.pathname !== "/login") router.replace("/login");
    };
    const keys = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setNavOpen(false);
        setPalette((value) => !value);
      }
    };
    window.addEventListener("cq:unauthorized", unauthorized);
    window.addEventListener("keydown", keys);
    return () => {
      window.removeEventListener("cq:unauthorized", unauthorized);
      window.removeEventListener("keydown", keys);
    };
  }, [router]);
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!navOpen) return;
    const focusable = () =>
      Array.from(
        navigationRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not(:disabled), summary, input:not(:disabled), [tabindex="0"]',
        ) || [],
      ).filter((element) => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setNavOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable(),
        first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      menuRef.current?.focus();
    };
  }, [navOpen]);
  function toggleTheme() {
    const value = !dark;
    setDark(value);
    document.documentElement.dataset.theme = value ? "dark" : "light";
    try {
      window.localStorage.setItem("cq_theme", value ? "dark" : "light");
    } catch {}
  }

  if (booting)
    return (
      <div className="boot">
        <Logo />
        <Loading text="Connecting to your private workspace…" />
      </div>
    );
  if (bootError)
    return (
      <div className="boot">
        <Logo />
        <ErrorBox error={bootError} retry={() => void boot()} />
      </div>
    );
  if (!user)
    return (
      <AuthPage
        setup={setup}
        authenticated={(value) => {
          setUser(value);
          setSetup(false);
          router.replace("/app");
        }}
      />
    );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {navOpen && (
        <button
          className="nav-scrim"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}
      <aside
        ref={navigationRef}
        id="workspace-navigation"
        className={`sidebar ${navOpen ? "open" : ""}`}
        aria-label="Workspace navigation"
        onClick={(event) => {
          if (
            event.target instanceof Element &&
            event.target.closest("a[href]")
          )
            setNavOpen(false);
        }}
      >
        <Link href="/app" className="brand-link">
          <Logo />
        </Link>
        <div className="sidebar-scroll">
          <div className="sidebar-section-title">WORKSPACE</div>
          <Link
            href="/app"
            className={`nav-link ${!caseId && pieces[2] !== "new" && !accountSettings && !administration ? "active" : ""}`}
          >
            <Icon name="matters" />
            All matters
            {!caseSearch && !includeArchived && cases.data && (
              <span className="nav-count">{number(cases.data.total)}</span>
            )}
          </Link>
          {user.role === "firm_admin" && (
            <Link
              href="/app/admin"
              className={`nav-link ${administration ? "active" : ""}`}
            >
              <Icon name="people" />
              Firm administration
            </Link>
          )}
          <Link
            href="/app/matters/new"
            className={`nav-link ${pieces[2] === "new" ? "active" : ""}`}
          >
            <Icon name="plus" />
            Create matter
          </Link>
          <Link
            href="/app/settings"
            className={`nav-link ${accountSettings ? "active" : ""}`}
          >
            <Icon name="shield" />
            Account security
          </Link>
          {caseId && (
            <>
              <div className="sidebar-matter">
                <span className="sidebar-section-title">CURRENT MATTER</span>
                <span>{matter.data?.matter_number || "Loading matter"}</span>
                <strong>{matter.data?.title || "Evidence workspace"}</strong>
              </div>
              <nav aria-label="Matter pages">
                {matterGroups.map((group) => (
                  <div className="nav-group" key={group.title}>
                    <div className="sidebar-section-title">{group.title}</div>
                    {matterNavigation
                      .filter(([key]) => group.keys.includes(key))
                      .map(([key, text, icon]) => (
                        <Link
                          key={key}
                          href={`/app/matters/${caseId}/${key}`}
                          className={`nav-link ${section === key || (section === "evidence" && key === "explorer") || (section === "imports" && key === "sources") ? "active" : ""}`}
                          aria-current={
                            section === key ||
                            (section === "evidence" && key === "explorer") ||
                            (section === "imports" && key === "sources")
                              ? "page"
                              : undefined
                          }
                        >
                          <Icon name={icon} />
                          {text}
                        </Link>
                      ))}
                  </div>
                ))}
              </nav>
            </>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="privacy-status" data-state={syncState}>
            <span className="status-dot" />
            <span>
              {syncState === "connected"
                ? "Connected to firm server"
                : syncState === "checking"
                  ? "Checking connection"
                  : syncState === "unavailable"
                    ? "Matter unavailable"
                    : "Reconnecting"}
              <small>CaseQuarry 0.4</small>
            </span>
            <Icon name="lock" size={15} />
          </div>
          <div className="user-row">
            <span className="avatar">
              {user.name
                .trim()
                .split(/\s+/)
                .map((part) => part[0])
                .slice(0, 2)
                .join("")
                .toUpperCase()}
            </span>
            <div>
              <strong>{user.name}</strong>
              <small>{user.email}</small>
            </div>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={async () => {
                try {
                  await post("/auth/logout");
                  setUser(null);
                  router.replace("/login");
                } catch (error) {
                  setBootError(error);
                }
              }}
            >
              <Icon name="logout" size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell" inert={navOpen}>
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            ref={menuRef}
            onClick={() => setNavOpen((value) => !value)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls="workspace-navigation"
          >
            <Icon name="menu" />
          </button>
          <div className="breadcrumb">
            <Link href="/app">Workspace</Link>
            {caseId && (
              <>
                <Icon name="chevron" size={13} />
                <span>{matter.data?.matter_number || "Matter"}</span>
              </>
            )}
            <Icon name="chevron" size={13} />
            <strong>
              {caseId
                ? matterNavigation.find(([key]) => key === section)?.[1] ||
                  "Evidence"
                : pieces[2] === "new"
                  ? "New matter"
                  : accountSettings
                    ? "Account security"
                    : administration
                      ? "Firm administration"
                      : "All matters"}
            </strong>
          </div>
          <div className="topbar-actions">
            <Link
              href="/app/settings"
              className="time-zone-status"
              aria-label={`Timezone settings, displaying ${getDisplayTimeZone(user.time_zone || "UTC")}`}
              title={`Account timezone: ${user.time_zone || "UTC"}${timeZoneSupported(user.time_zone || "UTC") ? "" : ". This browser displays UTC as a fallback."}`}
            >
              <Icon name="clock" size={14} />
              <span>
                {timeZoneSupported(user.time_zone || "UTC")
                  ? getDisplayTimeZone(user.time_zone || "UTC")
                  : "UTC fallback"}
              </span>
            </Link>
            <button
              className="command-trigger"
              aria-label="Quick navigation"
              onClick={() => setPalette(true)}
            >
              <Icon name="search" size={16} />
              <span>Search matters & pages</span>
              <kbd>{commandKey} K</kbd>
            </button>
            <button
              className="icon-button"
              aria-label={dark ? "Use light theme" : "Use dark theme"}
              onClick={toggleTheme}
            >
              <Icon name={dark ? "sun" : "moon"} size={19} />
            </button>
          </div>
        </header>
        <main
          id="main-content"
          className={`main-content ${caseId && ["explorer", "evidence", "emails"].includes(section) ? "explorer-main" : ""}`}
        >
          {caseId ? (
            matter.error ? (
              <ErrorBox error={matter.error} retry={matter.refresh} />
            ) : !matter.data ? (
              <Loading />
            ) : section === "overview" ? (
              <MatterOverview matter={matter.data} />
            ) : section === "review" ? (
              <ReviewQueue matter={matter.data} user={user} />
            ) : ["explorer", "evidence", "emails"].includes(section) ? (
              <Explorer
                matter={matter.data}
                emailOnly={section === "emails"}
                evidenceId={section === "evidence" ? pieces[4] : undefined}
              />
            ) : ["sources", "imports"].includes(section) ? (
              <SourcesPage
                matter={matter.data}
                batchId={section === "imports" ? pieces[4] : undefined}
              />
            ) : section === "people" ? (
              <PeoplePage matter={matter.data} />
            ) : section === "timeline" ? (
              <TimelinePage matter={matter.data} />
            ) : section === "network" ? (
              <NetworkPage matter={matter.data} />
            ) : section === "analytics" ? (
              <CommunicationAnalytics matter={matter.data} />
            ) : section === "productions" ? (
              <ProductionsPage matter={matter.data} user={user} />
            ) : section === "ai" ? (
              <SourceAssistant matter={matter.data} />
            ) : section === "audit" ? (
              <AuditPage matter={matter.data} />
            ) : ["holds", "issues", "tasks"].includes(section) ? (
              <GovernancePage
                matter={matter.data}
                kind={section as "holds" | "issues" | "tasks"}
              />
            ) : section === "reports" ? (
              <ReportsPage matter={matter.data} />
            ) : section === "settings" ? (
              <SettingsPage
                matter={matter.data}
                refresh={() => {
                  matter.refresh();
                  cases.refresh();
                }}
                user={user}
                modelPolicy={<LocalModelPolicy matter={matter.data} />}
              />
            ) : (
              <Empty
                icon="file"
                title="This page is unavailable"
                text="Use the matter navigation to open evidence, review or administration."
              />
            )
          ) : accountSettings ? (
            <AccountSecurity
              user={user}
              preferences={
                <TimeZoneSettings
                  key={user.id}
                  user={user}
                  saved={(updated) =>
                    setUser((current) =>
                      current?.id === updated.id &&
                      current.tenant_id === updated.tenant_id
                        ? updated
                        : current,
                    )
                  }
                />
              }
            />
          ) : administration ? (
            <FirmAdministration user={user} />
          ) : pieces[2] === "new" ? (
            <CreateMatter
              created={(id) => {
                cases.refresh();
                router.push(`/app/matters/${id}/overview`);
              }}
            />
          ) : (
            <MatterDashboard
              cases={cases}
              includeArchived={includeArchived}
              toggleArchived={setIncludeArchived}
              userId={user.id}
              userName={user.name}
              openFinder={() => setPalette(true)}
              filter={matterFilter}
              setFilter={setMatterFilter}
              hasPrevious={caseCursors.length > 1}
              previous={() => setCaseCursors((current) => current.slice(0, -1))}
              next={() => {
                if (cases.data?.next_cursor)
                  setCaseCursors((current) => [
                    ...current,
                    cases.data!.next_cursor,
                  ]);
              }}
            />
          )}
        </main>
      </div>
      {palette && (
        <CommandPalette
          key={user.id}
          caseId={caseId}
          navigation={matterNavigation}
          administrator={user.role === "firm_admin"}
          close={() => setPalette(false)}
          navigate={(path) => {
            setPalette(false);
            router.push(path);
          }}
        />
      )}
    </div>
  );
}

function AuthPage({
  setup,
  authenticated,
}: {
  setup: boolean;
  authenticated: (user: User) => void;
}) {
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await post<{ user: User; csrf_token: string }>(
        setup ? "/setup" : "/auth/login",
        data,
      );
      authenticated({ ...result.user, csrf_token: result.csrf_token });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-shell">
      <div className="auth-story">
        <Logo />
        <div>
          <span className="eyebrow">FIND THE FACTS. FOLLOW THE EVIDENCE.</span>
          <h1>
            A clearer view
            <br />
            of the record.
          </h1>
          <p>
            Preserve your sources. Connect the details.
            <br />
            Build your case on evidence you can verify.
          </p>
          <div className="auth-proof">
            <Icon name="shield" size={25} />
            <span>
              Self-hosted. Private by default.
              <br />
              <small>Search and review work without a model.</small>
            </span>
          </div>
        </div>
        <small className="auth-bottom">
          Built for careful investigation and human judgment.
        </small>
      </div>
      <div className="auth-form-container">
        <div className="auth-mobile-brand">
          <Logo />
        </div>
        <form className="auth-form" onSubmit={submit}>
          <span className="eyebrow">YOUR PRIVATE WORKSPACE</span>
          <h2>{setup ? "Set up CaseQuarry" : "Welcome back"}</h2>
          <p>
            {setup
              ? "Create the first firm administrator using the setup token from your server."
              : "Sign in to continue your evidence review."}
          </p>
          <ErrorBox error={error} />
          {setup && (
            <>
              <label>
                Setup token
                <input
                  name="token"
                  type="password"
                  required
                  autoComplete="off"
                />
              </label>
              <label>
                Firm or workspace name
                <input name="firm_name" required autoComplete="organization" />
              </label>
              <label>
                Your name
                <input name="name" required autoComplete="name" />
              </label>
            </>
          )}
          <label>
            Email address
            <input
              name="email"
              type="email"
              required
              autoComplete="username"
              placeholder="you@yourfirm.com"
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              required
              minLength={setup ? 12 : undefined}
              autoComplete={setup ? "new-password" : "current-password"}
            />
          </label>
          {setup ? (
            <small className="field-help">
              Use at least 12 characters. There is no default password.
            </small>
          ) : (
            <label>
              Authenticator code <span className="optional">if enabled</span>
              <input
                name="totp_code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="6-digit code"
              />
            </label>
          )}
          <button className="button primary auth-submit" disabled={busy}>
            {busy
              ? "Connecting…"
              : setup
                ? "Create private workspace"
                : "Sign in"}
            <Icon name="arrow" size={18} />
          </button>
          <p className="auth-notice">
            <Icon name="lock" size={15} />
            Access is limited to matters shared with your account.
          </p>
        </form>
      </div>
    </div>
  );
}

function MatterDashboard({
  cases,
  includeArchived,
  toggleArchived,
  userId,
  userName,
  openFinder,
  filter,
  setFilter,
  hasPrevious,
  previous,
  next,
}: {
  cases: ReturnType<typeof useResource<MatterPage>>;
  includeArchived: boolean;
  toggleArchived: (value: boolean) => void;
  userId: string;
  userName: string;
  openFinder: () => void;
  filter: string;
  setFilter: (value: string) => void;
  hasPrevious: boolean;
  previous: () => void;
  next: () => void;
}) {
  const rows = cases.data?.items || [];
  const [view, setView] = useState<"cards" | "list">("cards");
  useEffect(() => {
    let value: string | null = null;
    try {
      value = window.localStorage.getItem(`cq_matter_view.${userId}`);
    } catch {}
    setView(value === "list" ? "list" : "cards");
  }, [userId]);
  function changeView(value: "cards" | "list") {
    setView(value);
    try {
      window.localStorage.setItem(`cq_matter_view.${userId}`, value);
    } catch {}
  }
  return (
    <>
      <section className="firm-dashboard-hero">
        <div className="firm-dashboard-intro">
          <span className="eyebrow">
            FIRM WORKSPACE · {userName.split(" ")[0]}
          </span>
          <h1>
            Your matters.
            <br />A clearer perspective.
          </h1>
          <p>
            A focused place to follow the record, coordinate review and move
            your matters forward.
          </p>
          <div className="button-row">
            <Link className="button primary" href="/app/matters/new">
              <Icon name="plus" size={18} />
              New matter
            </Link>
            <button
              type="button"
              className="button secondary"
              onClick={openFinder}
            >
              <Icon name="search" size={17} /> Find a matter
            </button>
          </div>
        </div>
        <div className="firm-dashboard-summary">
          <span className="hero-summary-icon">
            <Icon name="matters" size={25} />
          </span>
          <strong>
            {cases.data && !cases.loading ? number(cases.data.total) : "—"}
          </strong>
          <span>Matters in this view</span>
          <small>
            {filter
              ? "Matching your current search"
              : includeArchived
                ? "Active and archived matters"
                : "Active matters you can access"}
          </small>
        </div>
      </section>
      <div className="workspace-assurance">
        <Icon name="shield" size={16} />
        <span>
          Preserved originals. Human review. External processing only with
          explicit consent.
        </span>
      </div>
      <MyWork userId={userId} />
      <section className="section matter-directory">
        <div className="section-heading">
          <h2>
            Your matters{" "}
            <span className="count-chip">{number(cases.data?.total)}</span>
          </h2>
          <div className="matter-directory-tools">
            <label className="archived-toggle">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(event) => toggleArchived(event.target.checked)}
              />
              <span>Include archived</span>
            </label>
            <label className="search-small">
              <Icon name="search" size={17} />
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Find a matter…"
                maxLength={200}
                aria-label="Find a matter"
              />
            </label>
            <div
              className="view-switch"
              role="group"
              aria-label="Matter layout"
            >
              <button
                type="button"
                aria-label="Card view"
                aria-pressed={view === "cards"}
                onClick={() => changeView("cards")}
              >
                <Icon name="grid" size={17} />
              </button>
              <button
                type="button"
                aria-label="List view"
                aria-pressed={view === "list"}
                onClick={() => changeView("list")}
              >
                <Icon name="list" size={17} />
              </button>
            </div>
          </div>
        </div>
        <ErrorBox error={cases.error} retry={cases.refresh} />
        {cases.loading ? (
          <Loading text="Loading your authorized matters…" />
        ) : !rows.length ? (
          <Empty
            icon="matters"
            title={filter ? "No matching matters" : "Make room for the facts."}
            text={
              filter
                ? "Try a different title, client or matter number."
                : "Create your first matter, then import evidence to begin your investigation."
            }
          >
            {!filter && (
              <Link className="button primary" href="/app/matters/new">
                <Icon name="plus" size={17} />
                Create your first matter
              </Link>
            )}
          </Empty>
        ) : (
          <div className="matter-grid" data-view={view}>
            {rows.map((item) => (
              <MatterCard key={item.id} matter={item} />
            ))}
          </div>
        )}
        {(hasPrevious || cases.data?.next_cursor) && (
          <div className="button-row">
            <button
              className="button secondary compact"
              disabled={!hasPrevious || cases.loading}
              onClick={previous}
            >
              Previous matters
            </button>
            <button
              className="button secondary compact"
              disabled={!cases.data?.next_cursor || cases.loading}
              onClick={next}
            >
              Next matters
            </button>
          </div>
        )}
      </section>
      <div className="workspace-footer">
        <Icon name="shield" size={16} />
        <span>
          CaseQuarry 0.4 · Professional judgment and verified source records
          remain essential.
        </span>
      </div>
    </>
  );
}

function MatterCard({ matter }: { matter: Matter }) {
  const stats = useResource<Stats>(`/cases/${matter.id}/stats`);
  return (
    <Link href={`/app/matters/${matter.id}/overview`} className="matter-card">
      <div className="matter-card-top">
        <span className="matter-glyph">
          <Icon name="matters" size={23} />
        </span>
        <Badge value={matter.archived_at ? "Archived" : "Active"} />
      </div>
      <div className="matter-card-identity">
        <span className="eyebrow">{matter.matter_number}</span>
        <h3>{matter.title}</h3>
        <p>
          {matter.client || "Client not specified"}
          {matter.case_type ? ` · ${matter.case_type}` : ""}
        </p>
      </div>
      <div className="matter-card-review">
        <div className="matter-card-metrics">
          <div>
            <strong>
              {stats.data ? number(stats.data.evidence_items) : "—"}
            </strong>
            <span>Evidence items</span>
          </div>
          <div>
            <strong>{stats.data ? number(stats.data.reviewed) : "—"}</strong>
            <span>Reviewed</span>
          </div>
        </div>
        {stats.data && (
          <div className="matter-review-progress">
            <div>
              <span>Human review</span>
              <strong>
                {stats.data.evidence_items
                  ? Math.round(
                      (stats.data.reviewed / stats.data.evidence_items) * 100,
                    )
                  : 0}
                %
              </strong>
            </div>
            <progress
              max={stats.data.evidence_items || 1}
              value={stats.data.reviewed}
              aria-label={`${number(stats.data.reviewed)} of ${number(stats.data.evidence_items)} evidence items reviewed`}
            />
          </div>
        )}
      </div>
      <div className="matter-card-bottom">
        <span>Updated {date(matter.updated_at)}</span>
        <Icon name="arrow" size={18} />
      </div>
      {Boolean(stats.error) && (
        <span className="card-warning">Evidence counts unavailable</span>
      )}
    </Link>
  );
}

function CreateMatter({ created }: { created: (id: string) => void }) {
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const matter = await post<Matter>(
        "/cases",
        Object.fromEntries(new FormData(event.currentTarget)),
      );
      created(matter.id);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">A NEW INVESTIGATION</span>
          <h1>Create a matter.</h1>
          <p>A separate workspace for your evidence, reviewers and findings.</p>
        </div>
      </div>
      <form className="panel form-panel" onSubmit={submit}>
        <div className="panel-heading">
          <span className="step-number">01</span>
          <div>
            <h2>Matter details</h2>
            <p>You can update these details later.</p>
          </div>
        </div>
        <ErrorBox error={error} />
        <div className="form-grid">
          <label>
            Matter number
            <input
              name="matter_number"
              required
              placeholder="2026-CIV-0042"
              maxLength={100}
            />
          </label>
          <label>
            Matter title
            <input
              name="title"
              required
              placeholder="Client v. Respondent"
              maxLength={300}
            />
          </label>
          <label>
            Client
            <input
              name="client"
              placeholder="Client or organization"
              maxLength={300}
            />
          </label>
          <label>
            Matter type
            <select name="case_type">
              <option value="Civil litigation">Civil litigation</option>
              <option>Internal investigation</option>
              <option>Regulatory inquiry</option>
              <option>Criminal defense</option>
              <option>Other</option>
            </select>
          </label>
          <label>
            Jurisdiction
            <input
              name="jurisdiction"
              placeholder="Court, province or jurisdiction"
              maxLength={300}
            />
          </label>
          <label className="full-width">
            Description
            <textarea
              name="description"
              rows={4}
              placeholder="What does this matter concern?"
              maxLength={5000}
            />
          </label>
        </div>
        <div className="form-info">
          <Icon name="lock" />
          <p>
            Only you will have access initially. Team access must be granted
            explicitly for this matter.
          </p>
        </div>
        <div className="form-actions">
          <Link href="/app" className="button secondary">
            Cancel
          </Link>
          <button className="button primary" disabled={busy}>
            {busy ? "Creating matter…" : "Create matter"}
            <Icon name="arrow" size={17} />
          </button>
        </div>
      </form>
    </>
  );
}
