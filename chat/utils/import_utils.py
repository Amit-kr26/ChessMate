import io
import logging
import re
from pathlib import Path
from typing import Optional

try:
    import chess
    import chess.pgn

    HAS_CHESS = True
except ImportError:
    HAS_CHESS = False
    chess = None

from utils.chess_engine import fen_is_valid
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def parse_pgn_text(pgn_text: str, max_games: int = 1) -> list[dict]:
    """Parse PGN text into structured game dicts.

    Uses streaming iterator to handle variations and not rely on split("\\n\\n").
    Returns list of dicts with keys: headers, moves_san, moves_uci, fens, pgn_text, valid.
    """
    if not pgn_text or not pgn_text.strip():
        return []

    if len(pgn_text) > 500_000:
        return [{"error": "PGN paste too large (>500k)", "valid": False}]
    if not HAS_CHESS:
        return [{"error": "python-chess not installed", "valid": False}]

    games = []
    pgn_io = io.StringIO(pgn_text.strip())
    count = 0
    while True:
        try:
            game = chess.pgn.read_game(pgn_io)
        except Exception as e:
            logger.warning("PGN parse error: %s", e)
            games.append({"error": str(e), "valid": False})
            break
        if game is None:
            break

        headers = dict(game.headers)
        board = game.board()
        moves_san = []
        moves_uci = []
        fens = [board.fen()]
        for move in game.mainline_moves():
            try:
                san = board.san(move)
                uci = move.uci()
                moves_san.append(san)
                moves_uci.append(uci)
                board.push(move)
                fens.append(board.fen())
            except Exception as e:
                logger.warning("Move push failed %s: %s", move, e)
                break

        try:
            exporter = chess.pgn.StringExporter(
                headers=True, variations=True, comments=True
            )
            pgn_str = game.accept(exporter)
        except Exception:
            pgn_str = pgn_text

        games.append(
            {
                "headers": headers,
                "moves_san": moves_san,
                "moves_uci": moves_uci,
                "fens": fens,
                "pgn_text": pgn_str,
                "event": headers.get("Event", ""),
                "site": headers.get("Site", ""),
                "white": headers.get("White", ""),
                "black": headers.get("Black", ""),
                "result": headers.get("Result", "*"),
                "white_elo": headers.get("WhiteElo", ""),
                "black_elo": headers.get("BlackElo", ""),
                "eco": headers.get("ECO", ""),
                "opening": headers.get("Opening", ""),
                "valid": True,
                "ply_count": len(moves_san),
            }
        )
        count += 1
        if count >= max_games:
            break

    return games


def validate_and_normalize_fen(fen: str) -> dict:
    """Validate FEN and return normalized version if valid."""
    valid, reason = fen_is_valid(fen)
    if not valid:
        return {"valid": False, "error": reason, "fen": fen}
    if HAS_CHESS:
        try:
            board = chess.Board(fen)
            normalized = board.fen()
            return {
                "valid": True,
                "fen": normalized,
                "original": fen,
                "is_check": board.is_check(),
                "is_checkmate": board.is_checkmate(),
                "is_stalemate": board.is_stalemate(),
                "turn": "white" if board.turn == chess.WHITE else "black",
                "legal_moves": [m.uci() for m in board.legal_moves][:5],
            }
        except Exception as e:
            return {"valid": False, "error": str(e), "fen": fen}
    return {"valid": True, "fen": fen.strip(), "original": fen}


def extract_fens_from_game(pgn_text: str, sample: str = "middle") -> list[str]:
    """Extract FENs from a PGN for prompt context or puzzle generation.

    sample: "start" | "middle" | "end" | "all"
    Uses board iteration; validates each.
    """
    games = parse_pgn_text(pgn_text, max_games=1)
    if not games or not games[0].get("valid"):
        return []
    fens = games[0].get("fens", [])
    if sample == "all":
        return fens
    if sample == "start":
        return fens[:2]
    if sample == "end":
        return fens[-2:]

    if len(fens) <= 4:
        return fens
    mid = len(fens) // 2
    start = max(1, mid - 1)
    end = min(len(fens), mid + 2)
    return fens[start:end]


def parse_uploaded_pgn_file(
    file_bytes: bytes, filename: str = "", max_games: int = 50
) -> tuple[list[dict], list[str]]:
    """Parse an uploaded PGN file (bytes) with size guard.

    Returns (games, errors). Limits to max_games to avoid UI hangs.
    """
    errors = []
    if not file_bytes:
        return [], ["empty file"]
    if len(file_bytes) > 10 * 1024 * 1024:
        return [], ["file too large (>10MB)"]
    try:

        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                import chardet

                enc = chardet.detect(file_bytes[:102400]).get("encoding") or "utf-8"
                text = file_bytes.decode(enc, errors="replace")
            except Exception:
                text = file_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return [], [f"decode failed: {e }"]

    if not HAS_CHESS:
        return [], ["python-chess not installed"]

    games = []
    pgn_io = io.StringIO(text)
    count = 0
    bad = 0
    while count < max_games:
        try:
            game = chess.pgn.read_game(pgn_io)
        except Exception as e:
            errors.append(f"parse error at game {count }: {e }")
            bad += 1
            if bad > 5:
                break
            continue
        if game is None:
            break

        try:
            exporter = chess.pgn.StringExporter(
                headers=True, variations=True, comments=True
            )
            pgn_str = game.accept(exporter)
        except Exception:
            pgn_str = ""

        headers = dict(game.headers)
        board = game.board()
        moves_san = []
        fens = [board.fen()]
        for move in game.mainline_moves():
            try:
                moves_san.append(board.san(move))
                board.push(move)
                fens.append(board.fen())
            except Exception:
                break
        games.append(
            {
                "headers": headers,
                "moves_san": moves_san,
                "fens": fens,
                "pgn_text": pgn_str,
                "white": headers.get("White", ""),
                "black": headers.get("Black", ""),
                "result": headers.get("Result", "*"),
                "opening": headers.get("Opening", ""),
                "valid": True,
                "ply_count": len(moves_san),
            }
        )
        count += 1

    return games, errors


def board_from_fen(fen: str):
    """Create a chess.Board from FEN, or None if invalid."""
    if not HAS_CHESS:
        return None
    valid, _ = fen_is_valid(fen)
    if not valid:
        return None
    try:
        return chess.Board(fen)
    except Exception:
        return None


def get_legal_moves(fen: str) -> list[str]:
    """Return UCI legal moves for a FEN."""
    board = board_from_fen(fen)
    if board is None:
        return []
    return [m.uci() for m in board.legal_moves]


def is_legal_move(fen: str, move_uci: str) -> bool:
    """Check if a UCI move is legal in the given FEN."""
    board = board_from_fen(fen)
    if board is None:
        return False
    try:
        move = chess.Move.from_uci(move_uci)
        return board.is_legal(move)
    except Exception:
        return False


def apply_move(fen: str, move_uci: str) -> Optional[str]:
    """Apply a UCI move to a FEN and return new FEN, or None if illegal."""
    board = board_from_fen(fen)
    if board is None:
        return None
    try:
        move = chess.Move.from_uci(move_uci)
        if not board.is_legal(move):
            return None
        board.push(move)
        return board.fen()
    except Exception:
        return None


LICHESS_API_BASE = "https://lichess.org"
CHESSCOM_API_BASE = "https://api.chess.com/pub"


def lichess_get_user_games_stub(
    username: str, max_games: int = 10, token: Optional[str] = None
) -> dict:
    if not username or not username.strip():
        return {"ok": False, "error": "username required", "games": []}
    if not re.match(r"^[a-zA-Z0-9_-]{2,30}$", username.strip()):
        return {"ok": False, "error": "invalid username format", "games": []}
    return {
        "ok": True,
        "stub": True,
        "message": "Provide username for public games (no token needed) or set LICHESS_TOKEN for private.",
        "fetch_url": f"{LICHESS_API_BASE}/api/games/user/{username.strip()}?max={max_games}&pgnInJson=true",
        "games": [],
    }


def _lichess_parse_ndjson(text: str, max_games: int) -> list[dict]:
    import json

    games = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # lichess pgnInJson: obj has 'pgn' string
            games.append(obj)
        except Exception:
            continue
        if len(games) >= max_games:
            break
    return games


def fetch_lichess_games(
    username: str, max_games: int = 10, token: Optional[str] = None, timeout: int = 10
) -> dict:
    import os as _os

    max_games = min(max(1, max_games), 50)
    username = username.strip()
    if not re.match(r"^[a-zA-Z0-9_-]{2,30}$", username):
        return {"ok": False, "error": "invalid username format", "games": []}
    try:
        import requests
    except ImportError:
        return {"ok": False, "error": "requests not installed", "games": []}

    tok = token or _os.getenv("LICHESS_TOKEN", "")
    url = f"{LICHESS_API_BASE}/api/games/user/{username}"
    params = {"max": max_games, "pgnInJson": "true", "clocks": "false", "evals": "false", "opening": "true"}
    headers = {"Accept": "application/x-ndjson", "User-Agent": "ChessMate/1.0 (chess RAG)"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, stream=True)
        if resp.status_code != 200:
            # 401 without token, 429 rate limited, 404 not found
            body = resp.text[:300] if hasattr(resp, "text") else ""
            if resp.status_code == 404:
                return {"ok": False, "error": f"user '{username}' not found", "games": []}
            if resp.status_code == 429:
                return {"ok": False, "error": "Lichess rate limited – try again in 1 min", "games": []}
            return {"ok": False, "error": f"Lichess API {resp.status_code}: {body}", "games": []}
        games = []
        # stream NDJSON
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                import json

                games.append(json.loads(line))
            except Exception:
                continue
            if len(games) >= max_games:
                break
        if not games:
            # fallback: try raw text read
            try:
                raw = resp.text if hasattr(resp, "text") else ""
                if raw.strip().startswith("{"):
                    games = _lichess_parse_ndjson(raw, max_games)
            except Exception:
                pass
        return {"ok": True, "games": games, "count": len(games)}
    except Exception as e:
        return {"ok": False, "error": str(e), "games": []}


def fetch_lichess_games_pgn(
    username: str, max_games: int = 10, timeout: int = 10, token: Optional[str] = None
) -> tuple[list[dict], list[str]]:
    res = fetch_lichess_games(username, max_games=max_games, timeout=timeout, token=token)
    if not res.get("ok"):
        return [], [res.get("error", "unknown error")]
    errors = []
    games = []
    for obj in res.get("games", []):
        pgn = obj.get("pgn", "")
        if not pgn:
            # sometimes obj is already pgn text wrapped
            pgn = obj.get("moves", "") or ""
            if not pgn:
                continue
            # construct minimal PGN from headers if needed
            headers = {k: str(v) for k, v in obj.items() if k not in ("pgn", "moves")}
            if headers:
                pgn = "\n".join([f'[{k} "{v}"]' for k, v in headers.items()]) + "\n\n" + pgn
        parsed = parse_pgn_text(pgn, max_games=1)
        if parsed and parsed[0].get("valid"):
            g = parsed[0]
            # enrich with lichess meta
            g["source"] = "lichess"
            g["lichess_id"] = obj.get("id", "")
            games.append(g)
        else:
            errors.append(f"skip invalid pgn for {obj.get('id','')}")
    return games, errors


def fetch_chesscom_games(
    username: str, max_games: int = 10, timeout: int = 10
) -> tuple[list[dict], list[str]]:
    username = username.strip()
    if not re.match(r"^[a-zA-Z0-9_-]{2,30}$", username):
        return [], ["invalid username format"]
    max_games = min(max(1, max_games), 50)
    try:
        import requests
    except ImportError:
        return [], ["requests not installed"]
    headers = {"User-Agent": "ChessMate/1.0 (chess RAG)"}
    try:
        arch_url = f"{CHESSCOM_API_BASE}/player/{username}/games/archives"
        r = requests.get(arch_url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            if r.status_code == 404:
                return [], [f"Chess.com user '{username}' not found"]
            return [], [f"Chess.com archives {r.status_code}: {r.text[:200]}"]
        data = r.json()
        archives = data.get("archives", [])
        if not archives:
            return [], ["no archives found"]
        games = []
        errors = []
        # last archives most recent
        for a in reversed(archives):
            if len(games) >= max_games:
                break
            try:
                rr = requests.get(a, headers=headers, timeout=timeout)
                if rr.status_code != 200:
                    errors.append(f"archive {a} {rr.status_code}")
                    continue
                j = rr.json()
                for g in j.get("games", []):
                    pgn = g.get("pgn", "")
                    if not pgn:
                        continue
                    parsed = parse_pgn_text(pgn, max_games=1)
                    if parsed and parsed[0].get("valid"):
                        pg = parsed[0]
                        pg["source"] = "chesscom"
                        pg["url"] = g.get("url", "")
                        games.append(pg)
                        if len(games) >= max_games:
                            break
                    else:
                        errors.append("skip invalid pgn")
            except Exception as e:
                errors.append(str(e))
                continue
        return games, errors
    except Exception as e:
        return [], [str(e)]


def _normalize_lichess_url(url: str) -> str:
    url = url.strip()
    # direct .pgn url
    if url.lower().endswith(".pgn"):
        return url
    # extract lichess game id 8-12 alphanum after lichess.org/
    m = re.search(r"lichess\.org/(?:game/export/)?([a-zA-Z0-9]{8,12})(?:/|$|#|\?)", url)
    if m:
        gid = m.group(1)
        return f"{LICHESS_API_BASE}/game/export/{gid}"
    # chess.com game url like https://www.chess.com/game/live/123... -> not direct PGN, need via chess.com api? fallback direct
    return url


def fetch_pgn_url(url: str, timeout: int = 10, max_games: int = 10) -> tuple[list[dict], list[str]]:
    url = url.strip()
    if not url or len(url) > 2048:
        return [], ["invalid url"]
    if not re.match(r"^https?://", url):
        return [], ["url must start with http(s)://"]
    # basic SSRF guard: block localhost/private
    if re.search(r"localhost|127\.0\.0\.1|0\.0\.0\.0|::1|10\.\d|192\.168|172\.(1[6-9]|2[0-9]|3[0-1])", url):
        return [], ["private url blocked"]
    norm = _normalize_lichess_url(url)
    try:
        import requests
    except ImportError:
        return [], ["requests not installed"]
    headers = {"User-Agent": "ChessMate/1.0 (chess RAG)"}
    try:
        r = requests.get(norm, headers=headers, timeout=timeout, stream=False)
        if r.status_code != 200:
            # try original url if normalized failed
            if norm != url:
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code != 200:
                    return [], [f"fetch {r.status_code}: {r.text[:200]}"]
            else:
                return [], [f"fetch {r.status_code}: {r.text[:200]}"]
        text = r.text
        if not text or len(text.strip()) < 10:
            return [], ["empty response"]
        # detect if response is PGN or JSON
        if text.strip().startswith("{") and '"pgn"' in text:
            # chess.com or lichess json wrapper
            import json

            try:
                j = json.loads(text)
                if isinstance(j, dict) and j.get("pgn"):
                    text = j["pgn"]
            except Exception:
                pass
        # check pgn signature
        if "[Event " not in text and "1. " not in text:
            return [], ["response does not look like PGN"]
        games = parse_pgn_text(text, max_games=max_games)
        valid = [g for g in games if g.get("valid")]
        if not valid:
            return [], ["no valid games in PGN"]
        return valid, []
    except Exception as e:
        return [], [str(e)]
