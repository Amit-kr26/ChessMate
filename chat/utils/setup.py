"""Resilient bulk ingestion – streaming PGN, bulk helpers, alias swap."""

import logging
import os
import io
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)

try:
    from utils.config import get_settings

    settings = get_settings()
except Exception:
    settings = None

try:
    from db_utils import init_db
except ImportError:
    from utils.db_utils import init_db

import chess
import chess.pgn
from elasticsearch import Elasticsearch
from elasticsearch import helpers

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def resolve_pgn_path() -> Path:

    env_path = os.getenv("PGN_PATH")
    if env_path:
        return Path(env_path)
    if settings and getattr(settings, "pgn_path", None):
        return Path(settings.pgn_path)

    return Path(__file__).resolve().parents[2] / "data" / "lichess_db.pgn"


def parse_elo(val: str) -> int | None:
    if not val or val.strip() in ("", "?", "-"):
        return None
    try:
        return int(val.strip())
    except Exception:
        try:
            return int(float(val.strip()))
        except Exception:
            return None


def get_chess_games(max_games: int | None = None, pgn_path: str | Path | None = None):
    """Stream PGN file game-by-game without loading full file into memory.

    Returns list of docs (dicts). Memory O(1) per game, not O(file size).
    """
    if max_games is None:
        if settings:
            max_games = getattr(settings, "max_index_docs", 2000)
        else:
            max_games = int(os.getenv("MAX_INDEX_DOCS", "2000"))

    path = Path(pgn_path) if pgn_path else resolve_pgn_path()
    logger.info("Reading PGN from %s (max %s games)", path, max_games)

    if not path.exists():
        logger.error("PGN file not found: %s", path)
        return []

    docs: list[dict] = []
    bads: list[str] = []
    count = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            while True:
                try:
                    game = chess.pgn.read_game(f)
                except Exception as e:
                    logger.warning("PGN read error at game %d: %s", count, e)
                    bads.append(str(e))
                    continue
                if game is None:
                    break

                headers = game.headers

                try:

                    board = game.board()
                    moves_san = []
                    for move in game.mainline_moves():
                        try:
                            san = board.san(move)
                            moves_san.append(san)
                            board.push(move)
                        except Exception as e:
                            logger.debug("SAN conversion failed: %s", e)
                            continue
                    moves_str = " ".join(moves_san) if moves_san else ""

                    data = {
                        "event": headers.get("Event", ""),
                        "site": headers.get("Site", ""),
                        "white": headers.get("White", ""),
                        "black": headers.get("Black", ""),
                        "result": headers.get("Result", "*"),
                        "utc_date": headers.get("UTCDate", ""),
                        "utc_time": headers.get("UTCTime", ""),
                        "white_elo": parse_elo(headers.get("WhiteElo", "")),
                        "black_elo": parse_elo(headers.get("BlackElo", "")),
                        "eco": headers.get("ECO", ""),
                        "opening": headers.get("Opening", ""),
                        "time_control": headers.get("TimeControl", ""),
                        "termination": headers.get("Termination", ""),
                        "moves": moves_str,
                    }

                    if not moves_str:
                        bads.append(f"empty moves at game {count }")
                        count += 1
                        if count >= max_games:
                            break
                        continue
                    docs.append(data)
                except (ValueError, KeyError) as e:
                    logger.warning("Skipping game %d due to header error: %s", count, e)
                    bads.append(str(e))
                    count += 1
                    if count >= max_games:
                        break
                    continue
                except Exception as e:
                    logger.warning("Skipping game %d: %s", count, e)
                    bads.append(str(e))
                    count += 1
                    if count >= max_games:
                        break
                    continue

                count += 1
                if count >= max_games:
                    break
                if count % 500 == 0:
                    logger.info("Parsed %d games...", count)
    except FileNotFoundError:
        logger.error("PGN file not found: %s", path)
        return []
    except Exception as e:
        logger.exception("Failed to read PGN: %s", e)
        return docs

    logger.info("Parsed %d games, %d bad", len(docs), len(bads))
    if bads:
        logger.debug("Bads sample: %s", bads[:3])
    return docs


def load_docs_in_elasticsearch(
    docs,
    es_url: str | None = None,
    index_name: str | None = None,
    chunk_size: int | None = None,
):
    """Bulk load docs into Elasticsearch with resilient settings.

    - Uses alias chess-rag -> chess-rag-v{timestamp} swap for zero downtime
    - Sets refresh_interval=-1 during bulk
    - Maps elo as integer, opening as text+keyword, utc_date as date
    """
    if settings:
        es_url = (
            es_url
            or getattr(settings, "elastic_url_local", None)
            or os.getenv("ELASTIC_URL_LOCAL", "http://localhost:9200")
        )
        index_name = index_name or getattr(settings, "index_name", "chess-rag")
        chunk_size = chunk_size or getattr(settings, "bulk_chunk_size", 500)
    else:
        es_url = es_url or os.getenv("ELASTIC_URL_LOCAL", "http://localhost:9200")
        index_name = index_name or os.getenv("INDEX_NAME", "chess-rag")
        chunk_size = chunk_size or int(os.getenv("BULK_CHUNK_SIZE", "500"))

    es_client = Elasticsearch(es_url, request_timeout=60, retry_on_timeout=True)

    try:
        if not es_client.ping():
            logger.warning("Elasticsearch ping failed at %s", es_url)
    except Exception as e:
        logger.warning("ES ping error: %s", e)

    import time as _time

    versioned_index = f"{index_name }-v{_time .strftime ('%Y%m%d%H%M%S')}"

    index_settings = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "-1",
            "analysis": {
                "analyzer": {
                    "chess_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        "mappings": {
            "properties": {
                "moves": {"type": "text", "analyzer": "chess_analyzer"},
                "white_player": {"type": "text"},
                "black_player": {"type": "text"},
                "white_elo": {"type": "integer"},
                "black_elo": {"type": "integer"},
                "event": {"type": "text"},
                "result": {"type": "keyword"},
                "opening": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "eco": {"type": "keyword"},
                "utc_date": {
                    "type": "date",
                    "format": "yyyy.MM.dd||yyyy-MM-dd||strict_date_optional_time",
                    "ignore_malformed": True,
                },
                "time_control": {"type": "keyword"},
            }
        },
    }

    try:
        es_client.options(ignore_status=[400, 404]).indices.delete(
            index=versioned_index
        )
    except Exception:
        pass

    try:
        es_client.indices.create(index=versioned_index, body=index_settings)
        logger.info("Created index %s", versioned_index)
    except Exception as e:
        logger.warning("Create index %s failed (may exist): %s", versioned_index, e)

        try:
            es_client.options(ignore_status=[400, 404]).indices.delete(
                index=versioned_index
            )
            es_client.indices.create(index=versioned_index, body=index_settings)
        except Exception as e2:
            logger.error("Failed to create index: %s", e2)
            raise

    def gen_actions():
        for doc in docs:

            utc_date = doc.get("utc_date", "")
            if utc_date and "." in utc_date:
                try:

                    dt = datetime.strptime(utc_date, "%Y.%m.%d")
                    utc_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
            new_doc = {
                "moves": doc.get("moves", ""),
                "white_player": doc.get("white", ""),
                "black_player": doc.get("black", ""),
                "white_elo": doc.get("white_elo"),
                "black_elo": doc.get("black_elo"),
                "event": doc.get("event", ""),
                "result": doc.get("result", "*"),
                "opening": doc.get("opening", ""),
                "eco": doc.get("eco", ""),
                "utc_date": utc_date,
                "time_control": doc.get("time_control", ""),
            }
            yield {"_index": versioned_index, "_source": new_doc}

    try:
        logger.info(
            "Bulk indexing %d docs (chunk %d) into %s",
            len(docs),
            chunk_size,
            versioned_index,
        )

        success, errors = helpers.bulk(
            es_client,
            gen_actions(),
            chunk_size=chunk_size,
            request_timeout=60,
            raise_on_error=False,
        )
        logger.info(
            "Bulk done: %d success, errors=%s",
            success,
            errors[:2] if errors else "none",
        )
    except Exception as e:
        logger.exception("Bulk indexing failed: %s", e)
        raise

    try:
        es_client.indices.put_settings(
            index=versioned_index, body={"refresh_interval": "1s"}
        )
        es_client.indices.refresh(index=versioned_index)
    except Exception as e:
        logger.warning("Failed to reset refresh_interval: %s", e)

    try:

        alias_exists = es_client.indices.exists_alias(name=index_name)
        if alias_exists:

            alias_info = es_client.indices.get_alias(name=index_name)
            old_indices = list(alias_info.keys())
            actions = []
            for idx in old_indices:
                actions.append({"remove": {"index": idx, "alias": index_name}})
            actions.append({"add": {"index": versioned_index, "alias": index_name}})
            es_client.indices.update_aliases(body={"actions": actions})
            logger.info(
                "Alias %s swapped from %s to %s",
                index_name,
                old_indices,
                versioned_index,
            )

            for idx in old_indices:
                if idx != versioned_index:
                    try:
                        es_client.indices.delete(index=idx)
                        logger.info("Deleted old index %s", idx)
                    except Exception:
                        pass
        else:

            if es_client.indices.exists(index=index_name):

                try:
                    es_client.indices.delete(index=index_name)
                    logger.info(
                        "Deleted bare index %s to replace with alias", index_name
                    )
                except Exception as e:
                    logger.warning("Could not delete bare index: %s", e)
            es_client.indices.put_alias(index=versioned_index, name=index_name)
            logger.info("Alias %s -> %s created", index_name, versioned_index)
    except Exception as e:
        logger.warning(
            "Alias swap failed: %s (index %s still usable)", e, versioned_index
        )

    try:
        from utils.cache_utils import invalidate_es_cache

        invalidate_es_cache()
    except Exception:
        pass

    logger.info(
        "Indexing complete. Docs: %d, Index: %s (alias %s)",
        len(docs),
        versioned_index,
        index_name,
    )
    return versioned_index


if __name__ == "__main__":
    logger.info("Initializing database...")
    host = "localhost"
    if settings:
        host = getattr(settings, "postgres_host", "localhost")
        if os.getenv("POSTGRES_HOST"):
            host = os.getenv("POSTGRES_HOST")
    try:
        init_db(host)
    except Exception as e:
        logger.warning("DB init failed (may already exist): %s", e)

    logger.info("Extracting info from %s", resolve_pgn_path())
    docs = get_chess_games()
    if not docs:
        logger.warning("No docs parsed; aborting ES load")
    else:
        load_docs_in_elasticsearch(docs)
