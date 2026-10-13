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

function showError(message: unknown) {
  error.textContent =
    typeof message === "string"
      ? message
      : "The connection could not be completed. Please try again.";
  error.hidden = false;
  status.textContent = "";
}

async function loadConnection() {
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
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  connect.disabled = true;
  forget.disabled = true;
  status.textContent = "Checking the server and its secure connection…";
  try {
    const result = await invoke<{
      server_url: string;
      setup_required: boolean;
    }>("connect_server", {
      serverUrl: address.value,
      allowLoopbackHttp: loopback.checked,
      remember: remember.checked,
    });
    address.value = result.server_url;
    forget.hidden = !remember.checked;
    status.textContent = result.setup_required
      ? "Connected. Complete the firm's initial setup in the workspace window."
      : "Connected. The firm workspace is open.";
  } catch (message) {
    showError(message);
  } finally {
    connect.disabled = false;
    forget.disabled = false;
  }
});

forget.addEventListener("click", async () => {
  error.hidden = true;
  forget.disabled = true;
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
    forget.disabled = false;
  }
});

void loadConnection();
