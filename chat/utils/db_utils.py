import os
import logging
import threading
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import DictCursor
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()
_POOL_MIN = 1
_POOL_MAX = 10


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            _pool = pg_pool.ThreadedConnectionPool(
                _POOL_MIN,
                _POOL_MAX,
                host=_cfg("POSTGRES_HOST", "localhost"),
                database=_cfg("POSTGRES_DB", "chess_assistant"),
                user=_cfg("POSTGRES_USER", "chess_assistant"),
                password=_cfg("POSTGRES_PASSWORD", "chess_assistant"),
                connect_timeout=5,
            )
            logger.info("DB pool created %s-%s", _POOL_MIN, _POOL_MAX)
        except Exception as e:
            logger.warning("DB pool init failed, fallback to direct connect: %s", e)
            _pool = None
        return _pool


def _pool_getconn():
    p = _get_pool()
    if p is None:
        return None
    try:
        return p.getconn()
    except Exception as e:
        logger.warning("pool getconn failed: %s", e)
        return None


def _pool_putconn(conn, close=False):
    p = _get_pool()
    if p is None or conn is None:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return
    try:
        if close:
            p.putconn(conn, close=True)
        else:
            p.putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _cfg(key: str, default: str) -> str:
    try:
        from utils.config import get_settings

        s = get_settings()

        mapping = {
            "POSTGRES_HOST": getattr(s, "postgres_host", default),
            "POSTGRES_DB": getattr(s, "postgres_db", default),
            "POSTGRES_USER": getattr(s, "postgres_user", default),
            "POSTGRES_PASSWORD": getattr(s, "postgres_password", default),
        }
        return str(mapping.get(key, os.getenv(key, default)))
    except Exception:
        return os.getenv(key, default)


def get_db_connection(host_p=None):
    """Get a Postgres connection.

    host_p: explicit host or None. If None, uses POSTGRES_HOST env / config.
    Preserves legacy call sites: save_conversation("postgres") and init_db("localhost").
    """
    if host_p is None:
        host = _cfg("POSTGRES_HOST", "localhost")
    else:

        env_host = os.getenv("POSTGRES_HOST")
        if env_host and host_p in ("postgres", "localhost"):

            if env_host == "postgres":
                host = env_host
            else:
                host = host_p
        else:
            host = host_p

    return psycopg2.connect(
        host=host,
        database=_cfg("POSTGRES_DB", "chess_assistant"),
        user=_cfg("POSTGRES_USER", "chess_assistant"),
        password=_cfg("POSTGRES_PASSWORD", "chess_assistant"),
    )


def _acquire_conn(host_p=None):
    """Acquire conn via pool if available, else direct connect (host-aware)."""
    c = _pool_getconn()
    if c is not None:

        try:
            c.cursor().execute("SELECT 1")
        except Exception:
            _pool_putconn(c, close=True)
            c = None
        else:
            return c

    return get_db_connection(host_p)


def _release_conn(conn, close=False):

    if _get_pool() is not None:
        _pool_putconn(conn, close=close)
    else:
        try:
            conn.close()
        except Exception:
            pass


def init_db(host="localhost", drop_existing=False):
    """Init DB non-destructively."""
    conn = _acquire_conn(host)
    try:
        with conn.cursor() as cur:
            if drop_existing:
                cur.execute("DROP TABLE IF EXISTS feedback")
                cur.execute("DROP TABLE IF EXISTS conversations")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    response_time FLOAT NOT NULL,
                    relevance TEXT NOT NULL,
                    relevance_explanation TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    eval_prompt_tokens INTEGER NOT NULL,
                    eval_completion_tokens INTEGER NOT NULL,
                    eval_total_tokens INTEGER NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    conversation_id TEXT REFERENCES conversations(id),
                    feedback INTEGER NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)

            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_relevance ON conversations(relevance)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_conversation ON feedback(conversation_id)"
            )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS puzzles (
                    id TEXT PRIMARY KEY,
                    fen TEXT NOT NULL,
                    moves TEXT NOT NULL,
                    rating INTEGER,
                    motifs TEXT,
                    source TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_puzzle_attempts (
                    id SERIAL PRIMARY KEY,
                    puzzle_id TEXT REFERENCES puzzles(id),
                    session_id TEXT NOT NULL,
                    solved BOOLEAN NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1,
                    interval_days INTEGER NOT NULL DEFAULT 0,
                    next_due TIMESTAMP WITH TIME ZONE NOT NULL,
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_puzzle_attempts_session ON user_puzzle_attempts(session_id, next_due)"
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _release_conn(conn)


def save_conversation(conversation_id, question, answer_data, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    conn = _acquire_conn("postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations
                (id, question, answer, model_used, response_time, relevance,
                relevance_explanation, prompt_tokens, completion_tokens, total_tokens,
                eval_prompt_tokens, eval_completion_tokens, eval_total_tokens, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    question,
                    answer_data["answer"],
                    answer_data["model_used"],
                    answer_data["response_time"],
                    answer_data["relevance"],
                    answer_data["relevance_explanation"],
                    answer_data["prompt_tokens"],
                    answer_data["completion_tokens"],
                    answer_data["total_tokens"],
                    answer_data["eval_prompt_tokens"],
                    answer_data["eval_completion_tokens"],
                    answer_data["eval_total_tokens"],
                    timestamp,
                ),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _release_conn(conn)


def save_feedback(conversation_id, feedback, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    conn = _acquire_conn("postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback (conversation_id, feedback, timestamp) VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP))",
                (conversation_id, feedback, timestamp),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _release_conn(conn)


def get_recent_conversations(limit=5, relevance=None):

    if relevance is not None:
        allowed = {"RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT", "UNKNOWN"}
        if relevance not in allowed:
            raise ValueError(f"Invalid relevance: {relevance }")
    conn = _acquire_conn("postgres")
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            query = """
                SELECT c.*, f.feedback
                FROM conversations c
                LEFT JOIN feedback f ON c.id = f.conversation_id
            """
            params = []
            if relevance:
                query += " WHERE c.relevance = %s"
                params.append(relevance)
            query += " ORDER BY c.timestamp DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, tuple(params))
            return cur.fetchall()
    finally:
        _release_conn(conn)


def get_feedback_stats():
    conn = _acquire_conn("postgres")
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN feedback > 0 THEN 1 ELSE 0 END),0) as thumbs_up,
                    COALESCE(SUM(CASE WHEN feedback < 0 THEN 1 ELSE 0 END),0) as thumbs_down
                FROM feedback
            """)
            return cur.fetchone()
    finally:
        _release_conn(conn)
