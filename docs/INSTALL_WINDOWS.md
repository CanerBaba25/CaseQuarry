# Run on Windows

This 0.1 development release is for synthetic evidence and evaluation. It is not cleared for confidential client matters. Use a private checkout on an encrypted disk and keep `.env` and `.data` out of source control.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24. Python 3.12 is selected by `.python-version`; uv can install it if necessary.

```powershell
uv sync --locked
uv run python scripts/tasks.py setup
uv run python scripts/tasks.py dev
```

Open `http://127.0.0.1:3000/setup`. Read the generated `CASEQUARRY_SETUP_TOKEN` from your local `.env`, enter it on the setup page and choose your administrator password. Setup tokens are one-time and expire; login does not bypass authentication on localhost. If setup has expired before completion, stop the API, replace the local token with a newly generated secret, and restart; do not delete a populated evidence database.

The API listens on `127.0.0.1:8000`; the web app proxies `/api` to it. This mode uses SQLite and an embedded durable worker. Ctrl+C stops the development processes. Data persists in `.data`; restarting does not erase it. If a port is occupied, stop the existing process or explicitly configure both the API address and frontend proxy.

Optional local OCR requires Tesseract and its language data. Standard installations are detected automatically; use `CASEQUARRY_TESSERACT_COMMAND` for another trusted executable location. Scanned PDFs/images remain visibly partial when recognition is disabled or unavailable. [Adapter documentation](ADAPTERS.md) describes settings, quality flags, Outlook limits and explicit read-only mailbox acquisition.

Run checks:

```powershell
uv run python scripts/tasks.py test
uv run python scripts/tasks.py lint
uv run python scripts/tasks.py typecheck
uv run python scripts/tasks.py smoke
```

`smoke` requires running services and checks availability only. `test` and browser commands require local QA assets, which are excluded from the public source distribution; a public checkout reports this accurately instead of pretending tests ran. Lint/typecheck/setup/dev do not require those assets.

Run the isolated real browser workflow with synthetic records:

```powershell
node apps/web/node_modules/@playwright/test/cli.js install chromium
uv run python scripts/tasks.py test-e2e
```

Where the local QA harness is available, the E2E task creates a separate database and short-lived test account, starts private loopback API/web processes, checks the import/search/review/export workflow and saves actual screenshots under ignored `.data/browser-e2e`. It never changes an existing matter or prints credentials.

## Docker Desktop option

Install Docker Desktop with Linux containers and Compose support, then:

```powershell
uv run python scripts/tasks.py init
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api worker
```

Only web port 3000 is published, bound to loopback. PostgreSQL, the API and the standalone durable worker share a private container network. `POSTGRES_PASSWORD` and the setup token must be present; Compose rejects missing credentials. No real `.env` is copied into images.

Docker was not installed on the initial development machine. Until actual Compose acceptance results are recorded, treat container deployment as unverified configuration. The tested local runtime is the uv/Node flow.

For confidential operation, require a completed security review, production TLS, encrypted disk/storage, independent backups and verified restore, preserved dependency notices, and professional workflow QA. Changing an environment flag does not satisfy those requirements. Store evidence outside automatically cloud-synchronized directories when matter policy requires local-only storage.

## Optional Rust verification

Install Rust using [official Rustup](https://rust-lang.org/tools/install/); Windows builds require Visual Studio C++ tools and a Windows SDK. Then `cargo build --release --locked`. `uv run casequarry evidence hash-file --path FILE --engine rust` and `uv run casequarry ingest inventory-mbox --path ARCHIVE --engine rust` run the native verifier. `--engine auto` selects the compiled binary when available, and `--engine python` uses the bounded fallback.
