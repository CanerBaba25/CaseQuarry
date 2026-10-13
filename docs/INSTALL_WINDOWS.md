# Install on Windows

The GitHub Release provides a Windows desktop installer and `casequarry-server-VERSION-windows-x64.zip`. The desktop is a client of the shared firm server, with no separate evidence database. [Server installation](SERVER_INSTALL.md) covers prerequisites, private storage, HTTPS, multiple computers and upgrades.

For source development, install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node24 and PostgreSQL16 or newer. PostgreSQL's [Windows page](https://www.postgresql.org/download/windows/) links the EDB installer and portable binary archive. Tools must include `pg_ctl`, `initdb`, `pg_dump` and `pg_restore`; standard locations are detected, or pass `--postgres-bin PATH` to setup.

```powershell
uv sync --locked
uv run python scripts/tasks.py setup
uv run python scripts/tasks.py dev
```

New setup generates protected private `.env` secrets and defaults to PostgreSQL. Its owned loopback cluster uses SCRAM authentication and a non-superuser application role; data lives under `%LOCALAPPDATA%/CaseQuarry/postgres`, outside the synchronized checkout. Windows new-init URLs normally use port55432. Existing configuration is preserved; populated SQLite installations require [verified legacy cutover](SERVER_INSTALL.md#existing-sqlite-installations).

For local development, open `http://127.0.0.1:3000/setup` and enter the one-time `CASEQUARRY_SETUP_TOKEN` from private `.env`. Setup and provider-encryption secrets are never printed. The API binds loopback8000 and the web app proxies requests to it. `dev` starts the exact configured owned PostgreSQL cluster, then API/web; Ctrl+C stops application processes and retains the database. `postgres-status`, `postgres-start` and `postgres-stop` manage only that cluster. Normal multi-computer deployment uses HTTPS and a standalone worker.

Optional Tesseract OCR requires local language data; `CASEQUARRY_TESSERACT_COMMAND` can select another trusted executable. Missing engines remain explicit partial extraction. See [adapter limits](ADAPTERS.md), [cloud consent/keys](CLOUD_AI_GUIDE.md) and [backup/recovery](BACKUP_RECOVERY.md).

`tasks.py lint`, `typecheck` and running-service `smoke` are available diagnostics. Test/browser/fixture/benchmark commands require local QA assets excluded from GitHub and report unavailable when absent. Docker Desktop can use the source Compose/HTTPS configuration in the server guide; Docker was unavailable on the current Windows validation host, so its deployment is not claimed as live-validated.

Optional Rust verification uses [Rustup](https://rust-lang.org/tools/install/), Visual Studio C++ tools and a Windows SDK, then `cargo build --release --locked`. CLI file/hash/manifest and MBOX inventory commands support `--engine rust`, `auto` or the Python fallback. The desktop has a separate Rust/Tauri build.
