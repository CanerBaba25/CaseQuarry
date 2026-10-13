# Install the shared firm server

Each firm uses one API, PostgreSQL database, worker and immutable evidence store. Browser and desktop clients connect to that same HTTPS firm address. A desktop installation is a client; copying database files between computers is not the synchronization mechanism. Transactional revision polling refreshes authorized client views after another client changes the shared server. Offline editing and multi-master replication are not implemented.

The GitHub Release provides a Windows desktop installer, a source ZIP, and separate `casequarry-server-VERSION-windows-x64.zip` and `casequarry-server-VERSION-linux-x64.zip` packages. Use the server ZIP matching the server operating system. Each contains the API/worker wheel, built Next standalone web application, installer/controller, dependency lock, retained runtime license notices and a file-hash manifest. PostgreSQL, Python/uv and Node are prerequisites rather than bundled runtimes.

## Prerequisites

Install Python3.12 or [uv](https://docs.astral.sh/uv/), Node20.9 or newer, and PostgreSQL16 or newer. PostgreSQL server/client tools include `initdb`, `pg_ctl`, `pg_dump` and `pg_restore`. Windows can use the [officially linked EDB installer or binary archive](https://www.postgresql.org/download/windows/); Linux can use its PostgreSQL packages. The installer creates a user-owned loopback-only PostgreSQL cluster with SCRAM authentication, checksums and a non-superuser application role, or uses an existing PostgreSQL URL supplied through an environment variable. Existing configuration and database contents are preserved.

## Install and start

Extract the server ZIP into a versioned application directory. Keep its private data directory outside OneDrive, Dropbox and other live synchronization folders. Run from the extracted package directory:

```powershell
uv run --no-project --python 3.12 python server.py install --data-dir "$env:LOCALAPPDATA\CaseQuarryServer"
uv run --no-project --python 3.12 python server.py start --data-dir "$env:LOCALAPPDATA\CaseQuarryServer"
```

On Linux:

```sh
sh install.sh --data-dir "$HOME/.local/share/casequarry-server"
uv run --no-project --python 3.12 python server.py start --data-dir "$HOME/.local/share/casequarry-server"
```

`install.ps1` is the Windows installation wrapper. Use `--postgres-bin` when tools are outside standard locations, or `--postgres-port` to select a free private database port. For an operator-managed database, set a private environment variable containing the PostgreSQL URL and add `--database-env VARIABLE_NAME` to installation. Do not place credentials in command-line arguments. The installer checks hashes, creates an isolated Python environment, installs locked dependencies, generates private setup/provider-encryption secrets, and applies static migrations. It does not create a firm or administrator automatically.

The controller starts API on loopback8000, web on loopback3000 and a standalone worker. It waits for API/web readiness and stops its owned application processes together if a component fails. `server.py stop --data-dir PATH` requests a clean supervisor stop; PostgreSQL data and its persistent server remain. `server.py status` reports configuration/supervisor presence without secrets. Keep the private `.env`, particularly the provider encryption key, with the recovery material. Never upload it to GitHub or copy it into clients.

Use `--loopback-development` only for an isolated local validation installation. Normal installation selects production cookie handling and requires an HTTPS proxy for firm access. Runtime `verify` checks every manifest file. An unsigned download still requires validating the GitHub Release checksum and publisher before installation.

## HTTPS and multiple computers

Place Caddy or another configured HTTPS reverse proxy in front of loopback3000. The included `Caddyfile` accepts `CASEQUARRY_FIRM_HOST`, the firm's real DNS hostname. [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) can provision certificates for a reachable configured domain. For a private LAN using its internal CA, add `tls internal` and have the administrator distribute/trust that CA on every browser and desktop computer; certificate validation must stay enabled. Do not expose PostgreSQL or API8000 to client computers.

Open the HTTPS firm address, enter the one-time setup token from the server's private `.env`, and create the first firm administrator. Add users and matter membership through the authenticated interface. Give each colleague that same firm address; the native client's saved address is device-local while evidence and review decisions stay on the server.

API launch commands disable forwarded-header rewriting. Authenticated rate limits use verified user/tenant identity. Anonymous sign-in requests traversing the same proxy share its peer bucket; changing proxy trust requires a reviewed network boundary and actual runtime validation. Database URLs for remote PostgreSQL should use certificate verification (`sslmode=verify-full`) and an operator-configured CA. The supplied local cluster and Compose database use private, unpublished connections.

## Existing SQLite installations

Normal setup and deployment use PostgreSQL. An explicit SQLite URL is retained for local QA and legacy recovery. Stop the old API/worker before cutover. Preserve the original SQLite file, storage directory and secrets. Supply the new empty PostgreSQL URL through private configuration, then run:

```sh
python -m casequarry.legacy_migration --source PATH_TO_OLD.sqlite --storage-root EXISTING_STORAGE --backup NEW_BACKUP.sqlite --services-stopped
```

The transfer makes a SQLite snapshot, verifies its exact known schema and every original's actual hash/size, locks an empty PostgreSQL target, copies rows in one transaction, checks counts/foreign keys/audit chains, and preserves the existing immutable storage root. It never modifies the source or replaces a populated target. Unknown schemas and failed integrity checks stop the migration. Change only the private database URL after verification. Keep the old SQLite snapshot until recovery and application checks pass.

## Backups and upgrades

Stop API/worker application services before a coordinated backup. Use PostgreSQL `pg_dump` custom format for the database, and copy the immutable storage directory, private `.env` and provider encryption key into protected backup storage. Encryption at rest, restricted access and an off-host copy are the operator's responsibility. Restore into a separate database and storage directory, verify original hashes and audit chains, and rehearse startup before relying on a backup. Do not overwrite the active installation during a restore.

For an upgrade, stop services, take that coordinated backup, install the new versioned package using the same data directory, and apply its forward migrations. The static schema checker refuses unknown revisions and drift; it never performs a destructive downgrade. If an interrupted supervisor leaves `run.json`, inspect the recorded process and private logs before removing only that stale marker.

## Compose deployment

The source distribution includes PostgreSQL/API/worker/web Compose configuration. `tasks.py init` generates private secrets, and the migration service runs before the API. PostgreSQL is unpublished on an internal network; only API/worker gain outbound connectivity for explicitly authorized vendor requests. The optional HTTPS overlay is:

```sh
docker compose -f docker-compose.yml -f infra/deploy/compose.https.yml up --build -d
```

Set `CASEQUARRY_FIRM_HOST` first. For a private CA, use the included LAN Caddyfile. Cloud capability does not enable transmission: firm policy, matter consent, the requesting user's encrypted key and per-job confirmation remain required; `CASEQUARRY_ALLOW_REMOTE_AI=false` is an operator kill switch. Docker deployment has not been executed on the current Windows validation host. Native Windows server installation is checked separately against actual PostgreSQL; Linux artifacts are built and checked by their release job.

## Artifact checks

Builders run `uv run python scripts/build_server.py --platform windows-x64|linux-x64 --output-dir .release-artifacts/server` on the matching operating system. Validation uses an isolated PostgreSQL schema:

```sh
uv run python scripts/verify_server.py --archive PATH_TO_SERVER.zip --database-env CASEQUARRY_TEST_POSTGRES_URL
```

It extracts and installs the artifact, runs its packaged API/worker/web, and checks authentication, independent-client shared matter access, durable import, exact original bytes, search and synchronization revisions. The URL stays in process environment, and only the exact generated QA schema is removed afterward. It does not drop the server database or change an operator's evidence.
