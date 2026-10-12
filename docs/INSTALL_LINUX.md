# Run on Linux or macOS

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24, then run from the checkout:

```sh
uv sync --locked
uv run python scripts/tasks.py setup
uv run python scripts/tasks.py dev
```

Open `http://127.0.0.1:3000/setup`; read the one-time setup token from local `.env` and choose an administrator password. The generated `.env` is mode 0600 on these platforms. Protect the data directory with equivalent owner-only permissions and an encrypted volume.

The local mode uses SQLite and an embedded durable worker. Data persists under `.data`. `.env` and the evidence store are ignored by Git and excluded from source releases. To use the CLI, configure the OS credential store: macOS Keychain or Linux Secret Service/KWallet. The client refuses a plaintext fallback. A short-lived `CASEQUARRY_TOKEN` may be supplied in the invoking process environment for automated private use; never place it in committed files or shell command arguments.

With Docker/Compose installed, `uv run python scripts/tasks.py init` followed by `docker compose up -d --build` runs private PostgreSQL/API/worker services and web on loopback port 3000. Compose has not yet been verified on the initial Windows machine. See [Windows installation](INSTALL_WINDOWS.md) for the exact deployment limits and required production safeguards.

For an offline installation, first obtain the pinned Python/npm distributions and container images through an approved connected environment. `uv sync --offline --locked` works only when every required distribution is cached. `npm ci --offline` similarly requires its cache. The application has no mandatory model or telemetry connection, but dependency installation is not automatically offline.

Portable checks are `uv run python scripts/tasks.py test`, `lint`, `typecheck`, and `smoke`. GNU Make aliases are optional; all supported tasks have Python equivalents.

For browser acceptance, run `node apps/web/node_modules/@playwright/test/cli.js install chromium`, then `uv run python scripts/tasks.py test-e2e`. Some Linux hosts need Playwright's documented system dependencies. The task uses an isolated synthetic database/account and writes real screenshots under ignored `.data/browser-e2e`.
