"""
database.py

Purpose: SQLAlchemy engine/session setup for the audit log's database
layer -- now Neon (managed Postgres) instead of a local SQLite file.
This is the only file that knows a connection string; api.py,
dashboard.py, and everything else still only ever talk to audit_log.py's
functions.

Configure via environment variable (or .env):
    DATABASE_URL - the Neon Postgres connection string, e.g.
        postgresql+psycopg2://user:password@ep-xxx.neon.tech/dbname?sslmode=require
    (see .env.example)
"""

import os
import env_loader  # loads .env automatically, same pattern as risk_scorer.py/dashboard.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set -- add it to your .env (see .env.example).")

# pool_pre_ping guards against Neon's serverless connection recycling
# (autosuspend/idle timeouts can close a pooled connection server-side
# without the pool knowing) -- without it, the first query on a stale
# connection would raise instead of transparently reconnecting.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()
