"""Async PostgreSQL database layer using asyncpg."""

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

# Module-level connection pool
_pool: Optional[asyncpg.Pool] = None


async def init_pool(dsn: str) -> None:
    """Create the connection pool. Call once at bot startup."""
    global _pool
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=5, ssl="require")
    logger.info("Database connection pool created.")


async def close_pool() -> None:
    """Close the pool. Call at bot shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


async def ensure_schema() -> None:
    """Create the schema and tables if they do not exist (idempotent)."""
    ddl = """
    CREATE SCHEMA IF NOT EXISTS lawyer_details;

    CREATE TABLE IF NOT EXISTS lawyer_details.users (
        id              SERIAL PRIMARY KEY,
        telegram_id     BIGINT NOT NULL UNIQUE,
        chat_id         BIGINT NOT NULL,
        lawyer_name     TEXT NOT NULL,
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_users_active
        ON lawyer_details.users (is_active) WHERE is_active = TRUE;

    CREATE TABLE IF NOT EXISTS lawyer_details.fetch_log (
        id              SERIAL PRIMARY KEY,
        run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        cl_type         CHAR(1) NOT NULL,
        target_date     TEXT NOT NULL,
        users_notified  INT NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'success',
        error_message   TEXT
    );

    CREATE TABLE IF NOT EXISTS lawyer_details.notification_log (
        id              SERIAL PRIMARY KEY,
        user_id         INT NOT NULL REFERENCES lawyer_details.users(id),
        sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        cl_type         CHAR(1) NOT NULL,
        target_date     TEXT NOT NULL,
        message_count   INT NOT NULL DEFAULT 1,
        UNIQUE(user_id, cl_type, target_date)
    );
    """
    async with _pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("Database schema ensured.")


# ---- User CRUD ----

async def upsert_user(telegram_id: int, chat_id: int, lawyer_name: str) -> None:
    """Register or update a user. If they exist, update lawyer_name and reactivate."""
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO lawyer_details.users (telegram_id, chat_id, lawyer_name, is_active, updated_at)
            VALUES ($1, $2, $3, TRUE, NOW())
            ON CONFLICT (telegram_id) DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                lawyer_name = EXCLUDED.lawyer_name,
                is_active = TRUE,
                updated_at = NOW()
        """, telegram_id, chat_id, lawyer_name.upper().strip())


async def deactivate_user(telegram_id: int) -> bool:
    """Soft-delete a user. Returns True if a row was updated."""
    async with _pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE lawyer_details.users SET is_active = FALSE, updated_at = NOW()
            WHERE telegram_id = $1 AND is_active = TRUE
        """, telegram_id)
        return result == "UPDATE 1"


async def get_user(telegram_id: int) -> Optional[asyncpg.Record]:
    """Fetch a single user by telegram_id."""
    async with _pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT * FROM lawyer_details.users WHERE telegram_id = $1
        """, telegram_id)


async def get_active_users() -> list[asyncpg.Record]:
    """Fetch all active users for scheduled notifications."""
    async with _pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM lawyer_details.users WHERE is_active = TRUE ORDER BY id
        """)


# ---- Notification dedup ----

async def was_notified(user_id: int, cl_type: str, target_date: str) -> bool:
    """Check if a user was already notified for this type+date combo."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 1 FROM lawyer_details.notification_log
            WHERE user_id = $1 AND cl_type = $2 AND target_date = $3
        """, user_id, cl_type, target_date)
        return row is not None


async def log_notification(user_id: int, cl_type: str, target_date: str, message_count: int) -> None:
    """Record that a notification was sent."""
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO lawyer_details.notification_log (user_id, cl_type, target_date, message_count)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, cl_type, target_date) DO NOTHING
        """, user_id, cl_type, target_date, message_count)


# ---- Fetch log ----

async def log_fetch(cl_type: str, target_date: str, users_notified: int,
                    status: str = "success", error_message: str = None) -> None:
    """Log a scheduled fetch run."""
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO lawyer_details.fetch_log (cl_type, target_date, users_notified, status, error_message)
            VALUES ($1, $2, $3, $4, $5)
        """, cl_type, target_date, users_notified, status, error_message)
