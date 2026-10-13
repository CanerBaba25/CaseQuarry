# Install on Linux

The release's `casequarry-server-VERSION-linux-x64.zip` contains the API/worker wheel, Next standalone web and installer. Use the matching operating-system build; Windows native dependencies cannot be relabeled for Linux. See [shared server installation](SERVER_INSTALL.md) for PostgreSQL, HTTPS, storage, legacy migration and upgrades. Other client computers use the same firm browser URL; the current desktop installer targets Windows.

For source development, install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node24 and PostgreSQL16 or newer. Debian/Ubuntu tools may be under `/usr/lib/postgresql/16/bin`:

```sh
uv sync --locked
uv run python scripts/tasks.py setup --postgres-bin /usr/lib/postgresql/16/bin
uv run python scripts/tasks.py dev
```

New private configuration defaults to PostgreSQL on loopback5432 and is mode0600. Managed database files live under `~/.local/share/casequarry/postgres`; initialization refuses an existing unmanaged directory. `dev` can start the exact owned cluster, while `postgres-status`, `postgres-start` and `postgres-stop` expose its lifecycle without credentials. Existing configurations are preserved. An explicit SQLite URL remains for local QA and guarded recovery.

Local development opens `http://127.0.0.1:3000/setup` using the one-time `.env` token. Persistent data must stay outside live synchronization folders. Other computers connect through a configured HTTPS firm hostname to one central API/database/evidence store; authorized revision polling refreshes views after changes.

Configure Linux Secret Service/KWallet for CLI profiles; there is no plaintext token fallback. Private automation can use process `CASEQUARRY_TOKEN`, without committed files or token arguments. Optional OCR uses distribution Tesseract/language-data packages; [adapter documentation](ADAPTERS.md) states bounds and missing-runtime behavior.

Compose includes static migrations and unpublished PostgreSQL. API/worker have outbound connectivity for explicitly authorized optional vendor requests; the HTTPS overlay accepts the firm's actual hostname. Docker was unavailable on the Windows host. Linux artifacts require their release job's native validation, and deployment/restore must be checked on the operator's host.

Offline installation requires cached pinned Python/npm/runtime distributions; `uv sync --offline --locked` and `npm ci --offline` cannot supply missing files. Cloud transmission requires [firm policy, matter consent and user keys](CLOUD_AI_GUIDE.md). Source lint/typecheck/smoke do not require private QA; local test/browser/benchmark tasks report unavailable when excluded assets are absent. Optional native verification uses [Rustup](https://rust-lang.org/tools/install/) and `cargo build --release --locked`.
