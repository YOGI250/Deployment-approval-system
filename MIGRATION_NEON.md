# Migrating the database layer: SQLite → Neon Postgres

Scope: **only** `app/audit_log.py` and its database plumbing changed.
`api.py`, `dashboard.py`, `accuracy_metrics.py`, the Azure pipeline, and
every request/response shape are untouched.

## What changed

| File | Change |
|---|---|
| `app/models.py` | **New.** SQLAlchemy ORM model `AuditLog`, one column per existing SQLite column, same names/types. |
| `app/database.py` | **New.** Engine/session setup, reads `DATABASE_URL` from the environment. |
| `app/audit_log.py` | **Rewritten internals only.** Same 7 functions, same names, same signatures, same return shapes: `init_db()`, `check_connection()`, `log_decision()`, `update_outcome()`, `update_verification()`, `update_recovery()`, `get_all_logs()`. |
| `requirements.txt` | Added `sqlalchemy`, `psycopg2-binary`. |
| `.env.example` | Added `DATABASE_URL`. |

Note: your spec referred to `log_prediction()` — the real function `api.py`
imports is `log_decision()`. That name was kept as-is (renaming it would
break `api.py`'s import).

Nothing in `api.py`, `dashboard.py`, or `accuracy_metrics.py` needs to
change — they only ever call these 7 functions, never touch SQL directly.

## Design decisions that keep the API/JSON identical

- **`created_at` stays a plain string** (`datetime.now().isoformat()`),
  not a native Postgres `TIMESTAMP`. If it were a real timestamp,
  SQLAlchemy would hand back a `datetime` object with a different
  `str()` format (space instead of `T`), which would silently change
  what the dashboard displays and what `/history` serializes.
- **`degraded`, `policy_override`, `rollback_recommended` stay
  `Integer` (0/1)**, not `Boolean`. FastAPI's default JSON encoder would
  turn a `Boolean` column into `true`/`false` in the `/history` response
  — a response shape change your spec explicitly forbids.
- **`triggered_policies` and `health_check` stay `Text`** (JSON-encoded
  strings), with the existing manual `json.dumps`/`json.loads` in
  `audit_log.py` untouched — not a native Postgres `JSON` column, which
  would return already-parsed Python objects and break that logic.
- **Ordering by `created_at DESC`** works the same way it did in
  SQLite: it's a lexicographic sort on a zero-padded ISO 8601 string,
  which is equivalent to chronological order either way.

## Steps

### 1. Create the Neon database

1. Sign up / log in at neon.tech, create a project.
2. In the project dashboard → **Connection Details**, copy the pooled
   connection string. It looks like:
   ```
   postgresql://neondb_owner:AbC123@ep-cool-name-12345-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

### 2. Install the new dependencies

```bash
pip install -r requirements.txt --break-system-packages
```

(Adds `sqlalchemy` and `psycopg2-binary`.)

### 3. Set `DATABASE_URL`

Copy the connection string from step 1 into your **real** `.env`
(`.env.example` only has a placeholder), and change the scheme prefix
from `postgresql://` to `postgresql+psycopg2://` so SQLAlchemy picks
the right driver:

```
DATABASE_URL=postgresql+psycopg2://neondb_owner:AbC123@ep-cool-name-12345-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
```

### 4. Create the table

Nothing manual needed — `api.py` already calls `init_db()` on startup
(line ~46), unchanged. That now runs
`Base.metadata.create_all(bind=engine)`, which creates the `audit_log`
table in Neon on first run if it doesn't exist yet, and is a no-op
every time after. You can also trigger it directly:

```bash
cd app
python3 audit_log.py
```

Expected output:
```
Database ready (Neon Postgres)
Existing rows: 0
```

### 5. (Optional) Carry over existing SQLite history

If `data/audit_log.db` already has rows you want to keep, run this
once, after step 4, to copy them into Neon. It's a standalone script —
it doesn't touch any project file:

```python
# migrate_sqlite_to_neon.py — run once, then delete
import sqlite3
from app.database import SessionLocal
from app.models import AuditLog

conn = sqlite3.connect("data/audit_log.db")
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()]
conn.close()

session = SessionLocal()
for row in rows:
    row.pop("id", None)  # let Neon assign fresh primary keys
    session.add(AuditLog(**row))
session.commit()
session.close()
print(f"Copied {len(rows)} rows to Neon.")
```

### 6. Run and verify

```bash
cd app
uvicorn api:app --reload
```

Hit `/predict` a couple of times, then:

```bash
curl http://127.0.0.1:8000/history -H "X-API-Key: <your key>"
```

Confirm the JSON shape is identical to what you saw against SQLite
(same fields, `0`/`1` not `true`/`false`, `triggered_policies` as an
array). Then load the Streamlit dashboard as usual — it reads from
`/history` over HTTP and has no idea the database changed underneath.

## Rollback

Everything is in git. If anything goes wrong, revert `app/audit_log.py`,
`requirements.txt`, and `.env.example`, and delete `app/models.py` /
`app/database.py` — `audit_log.db` (the SQLite file) was never touched
or deleted, so the old code path still works immediately.
