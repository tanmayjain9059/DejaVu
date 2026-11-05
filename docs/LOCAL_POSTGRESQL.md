# Local PostgreSQL for LostLink

This runs a local PostgreSQL 16 database for development. It does not provision a hosted/production database.

## Start PostgreSQL

From the repository root:

```bash
docker compose up -d postgres
docker compose ps
```

Wait until the `postgres` service reports healthy. The data persists in the named Docker volume `lostlink-postgres-data`.

## Point the application at PostgreSQL

Set these values in your local `.env` file (do not commit `.env`):

```dotenv
DATABASE_URL=postgresql://lostlink:local-dev-only-change-me@127.0.0.1:5432/lostlink
DATABASE_POOL_MAX_SIZE=5
SESSION_SECRET=<generate-a-unique-random-secret>
DEMO_MODE=false
SESSION_HTTPS_ONLY=false
```

The default database password is for local development only. To use a different password, start Compose with `LOSTLINK_DB_PASSWORD` set and use the same password in `DATABASE_URL`. If the named volume was initialized with an earlier password, changing the environment variable alone does not change the existing database user's password.

Install dependencies and run the application as usual:

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

On startup, LostLink creates/updates its current schema. Check `http://127.0.0.1:8000/health/ready`; a ready response confirms the application can execute a database query.

## Stop and reset

- Stop without deleting data: `docker compose stop postgres`
- Stop the service: `docker compose down`
- **Delete all local database data** (destructive): `docker compose down -v`

Do not use the example password or this Compose configuration as a public production deployment. Production needs a managed PostgreSQL instance, TLS, restricted network access, managed secrets, backups with tested restoration, and persistent private image/evidence storage. Setting `DATABASE_URL` does not automatically migrate existing SQLite records.
