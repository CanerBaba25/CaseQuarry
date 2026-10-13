import { invoke } from "@tauri-apps/api/core";
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
let busy = false;

function setBusy(value: boolean) {
  busy = value;
  for (const control of [address, remember, loopback, connect, forget]) {
    control.disabled = value;
  }
}

function showError(message: unknown) {
  error.textContent =
    typeof message === "string"
      ? message
      : "The connection could not be completed. Please try again.";
  error.hidden = false;
  status.textContent = "";
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
      status.textContent =
        "Saved server address loaded. Connect when you are ready.";
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
  status.textContent = "Checking the server and its secure connection…";
  try {
    const result = await invoke<{
      server_url: string;
      setup_required: boolean;
    }>("connect_server", submitted);
    address.value = result.server_url;
    forget.hidden = !submitted.remember;
    status.textContent = result.setup_required
      ? "Connected. Complete the firm's initial setup in the workspace window."
      : "Connected. The firm workspace is open.";
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
    status.textContent =
      "Saved server address removed. Sign out in an open workspace before leaving it.";
    address.focus();
  } catch (message) {
    showError(message);
  } finally {
    setBusy(false);
  }
});

void loadConnection();
