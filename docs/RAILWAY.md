# Railway deployment (experimental)

This configuration is for a **separate test installation**. It has not yet passed a live Railway acceptance test. The original installation guide targets Ubuntu 24.04 + PostgreSQL 16 + systemd, and its timers are **not** included in this Dockerfile.

## Components

- Web service: built from repository-root Dockerfile in the `railway-deployment` branch.
- PostgreSQL **16** with persistent Railway volume (do not silently use a different major version).
- Collectors, precompute, AI tasks and Telegram bot: separate worker services still to be configured, each with the correct command and scheduler.
- WB storefront-price browser collector: separate Russian-IP VPS as documented in `docs/RUSSIAN-SERVER.md`.

## Before starting web

1. Create an isolated PostgreSQL 16 database and confirm its persistent storage.
2. Set `DATABASE_URL` to private connection string. Set `AIS_MASTER_KEY` to a locally generated, securely backed-up Fernet key. Set `SITE_URL` to the actual HTTPS Railway domain. Never commit or paste secrets.
3. Apply database migrations **once**, in a controlled one-off job: `python -c 'import stometric.web; from stometric import db; print(db.migrate())'`.
4. Create first administrator through an appropriately secured, interactive one-off `python scripts/bootstrap.py` session. Do not put administrator credentials into build arguments, command-line flags, repository, logs or service environment variables.
5. Only then expose the HTTPS domain and validate login, authorization, and one test shop's numbers.

The service does **not** run migrations or create an administrator automatically. This avoids concurrent migration/bootstrap runs on scaling and deploy retries.

## Important limitations

- The Python image uses an ephemeral filesystem: persistent generated files, uploads and archives must be explicitly moved to persistent storage or provisioned via a volume with reviewed paths and permissions.
- `systemd` is not available in Railway containers. Workers and timed jobs need independent Railway services and tested schedule semantics.
- No API marketplace keys should be supplied until permission isolation and financial calculations have been verified.
- No automatic card editing, repricing, advertising changes, or paid AI background processes should be enabled before separate approval and acceptance.
- Verify license permissions for copying/modifying/operating this project with its copyright holder (see `LICENSE-STATUS.md`).
