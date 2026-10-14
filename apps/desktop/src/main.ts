import { invoke } from "@tauri-apps/api/core";
import {
  createTranslator,
  loadCatalog,
  locales,
  normalizeLanguage,
  type Language,
} from "../../../packages/i18n";
import "./styles.css";

type Connection = { server_url: string; allow_loopback_http: boolean };
const element = <T extends HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const form = element<HTMLFormElement>("connection-form");
const address = element<HTMLInputElement>("server-url");
const remember = element<HTMLInputElement>("remember-server");
const loopback = element<HTMLInputElement>("allow-loopback");
const connect = element<HTMLButtonElement>("connect-button");
const forget = element<HTMLButtonElement>("forget-button");
const error = element<HTMLDivElement>("connection-error");
const status = element<HTMLDivElement>("connection-status");
const languageSelect = element<HTMLSelectElement>("interface-language");
let busy = false;
let language: Language = "en";
let t = createTranslator(language);
let statusMessage = "";
let errorMessage = "";
const languageStorage = "casequarry.connection.language";

for (const locale of locales) {
  const option = document.createElement("option");
  option.value = locale.code;
  option.textContent = locale.nativeName;
  languageSelect.append(option);
}

function renderMessages() {
  document.documentElement.lang = language;
  document.title = t("CaseQuarry — {0}", { "0": t("Firm connection") });
  document.querySelectorAll<HTMLElement>("[data-i18n]").forEach((node) => {
    const message = node.dataset.i18n;
    if (message) node.textContent = t(message);
  });
  element("connection-footer").textContent = t(
    "Your password is entered only in the firm workspace. Use the desktop's {0} menu to return here.",
    { "0": t("Connection") },
  );
  status.textContent = statusMessage ? t(statusMessage) : "";
  const http = errorMessage.match(
    /^The server returned HTTP (\d{3})\. Confirm the CaseQuarry website address with your administrator\.$/,
  );
  error.textContent = http
    ? t(
        "The server returned HTTP {0}. Confirm the CaseQuarry website address with your administrator.",
        { "0": http[1] },
      )
    : errorMessage
      ? t(errorMessage)
      : "";
}

async function chooseLanguage(selected: Language, persist: boolean) {
  const catalog = await loadCatalog(selected);
  const translate = createTranslator(selected, catalog);
  await invoke("set_language", {
    language: selected,
    labels: {
      connection: translate("Connection"),
      firmConnection: translate("Firm connection…"),
      closeWorkspace: translate("Close workspace"),
      exitCaseQuarry: translate("Exit CaseQuarry"),
      edit: translate("Edit"),
      undo: translate("Undo"),
      redo: translate("Redo"),
      cut: translate("Cut"),
      copy: translate("Copy"),
      paste: translate("Paste"),
      selectAll: translate("Select all"),
    },
  });
  language = selected;
  t = translate;
  languageSelect.value = selected;
  if (persist) {
    try {
      localStorage.setItem(languageStorage, selected);
    } catch {
      /* Public UI preference only. */
    }
  }
  renderMessages();
}

function setStatus(message: string) {
  statusMessage = message;
  renderMessages();
}

function setBusy(value: boolean) {
  busy = value;
  for (const control of [
    address,
    remember,
    loopback,
    connect,
    forget,
    languageSelect,
  ]) {
    control.disabled = value;
  }
}

function showError(message: unknown) {
  errorMessage =
    typeof message === "string"
      ? message
      : "The connection could not be completed. Please try again.";
  error.hidden = false;
  setStatus("");
}

async function loadConnection() {
  setBusy(true);
  try {
    const saved = await invoke<Connection | null>("get_connection");
    if (saved) {
      address.value = saved.server_url;
      loopback.checked = saved.allow_loopback_http;
      forget.hidden = false;
      if (saved.allow_loopback_http) {
        loopback.closest("details")!.open = true;
      }
      setStatus("Saved server address loaded. Connect when you are ready.");
    }
  } catch (message) {
    showError(message);
    forget.hidden = false;
  } finally {
    setBusy(false);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const submitted = {
    serverUrl: address.value,
    allowLoopbackHttp: loopback.checked,
    remember: remember.checked,
  };
  error.hidden = true;
  setBusy(true);
  setStatus("Checking the server and its secure connection…");
  try {
    const result = await invoke<{
      server_url: string;
      setup_required: boolean;
    }>("connect_server", submitted);
    address.value = result.server_url;
    forget.hidden = !submitted.remember;
    setStatus(
      result.setup_required
        ? "Connected. Complete the firm's initial setup in the workspace window."
        : "Connected. The firm workspace is open.",
    );
  } catch (message) {
    showError(message);
  } finally {
    setBusy(false);
  }
});

forget.addEventListener("click", async () => {
  if (busy) return;
  error.hidden = true;
  setBusy(true);
  try {
    await invoke("forget_connection");
    address.value = "";
    loopback.checked = false;
    forget.hidden = true;
    setStatus(
      "Saved server address removed. Sign out in an open workspace before leaving it.",
    );
    address.focus();
  } catch (message) {
    showError(message);
  } finally {
    setBusy(false);
  }
});

languageSelect.addEventListener("change", async () => {
  if (busy) return;
  const selected = normalizeLanguage(languageSelect.value);
  setBusy(true);
  try {
    await chooseLanguage(selected, true);
  } catch {
    languageSelect.value = language;
    showError("The interface language could not be loaded. Please try again.");
  } finally {
    setBusy(false);
  }
});

async function initialize() {
  setBusy(true);
  let selected: Language = "en";
  try {
    selected = normalizeLanguage(localStorage.getItem(languageStorage));
  } catch {
    /* Use English. */
  }
  try {
    await chooseLanguage(selected, false);
  } catch {
    renderMessages();
    languageSelect.value = "en";
    showError("The interface language could not be loaded. Please try again.");
  }
  await loadConnection();
}

void initialize();
