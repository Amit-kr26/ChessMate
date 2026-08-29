import atexit
import logging
import shutil
import threading
from functools import lru_cache
from typing import Optional

try:
    import chess
    import chess.engine

    HAS_CHESS = True
except ImportError:
    HAS_CHESS = False
    chess = None

from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PIECE_VALUES = {
    1: 100,
    2: 320,
    3: 330,
    4: 500,
    5: 900,
    6: 0,
}

BLUNDER_THRESHOLDS = {
    "brilliant": -50,
    "good": 25,
    "inaccuracy": 50,
    "mistake": 100,
    "blunder": 300,
}


def _material_eval_fen(fen: str) -> int:
    """Fast material estimator when Stockfish unavailable.

    Returns centipawn score from White's perspective (positive = White better).
    Does not consider position; purely material.
    """
    if not HAS_CHESS:
        return 0
    try:
        board = chess.Board(fen)
    except Exception:
        return 0
    score = 0
    for piece_type in range(1, 7):
        w = len(board.pieces(piece_type, chess.WHITE))
        b = len(board.pieces(piece_type, chess.BLACK))
        score += (w - b) * PIECE_VALUES.get(piece_type, 0)

    return score


def classify_move(cp_loss: Optional[int]) -> str:
    """Classify a move based on centipawn loss from engine best line."""
    if cp_loss is None:
        return "unknown"
    if cp_loss >= BLUNDER_THRESHOLDS["blunder"]:
        return "blunder"
    if cp_loss >= BLUNDER_THRESHOLDS["mistake"]:
        return "mistake"
    if cp_loss >= BLUNDER_THRESHOLDS["inaccuracy"]:
        return "inaccuracy"
    return "good"


def fen_is_valid(fen: str) -> tuple[bool, str]:
    """Validate a FEN string.

    Returns (is_valid, reason). Uses python-chess validation when available,
    otherwise stricter structural checks (fail-closed).
    """
    if not fen or not isinstance(fen, str):
        return False, "empty FEN"

    if len(fen) > 200:
        return False, "FEN too long"
    parts = fen.strip().split()
    if len(parts) != 6:
        return False, f"FEN must have 6 fields, got {len (parts )}"
    if HAS_CHESS:
        try:
            board = chess.Board(fen)
            try:
                valid = board.is_valid()
            except Exception:
                valid = True
            if not valid:
                return False, "board.is_valid() == False (e.g. missing kings)"
            return True, "ok"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"invalid FEN: {e }"

    import re

    board_part, active, castle, ep, half, full = parts
    if len(board_part.split("/")) != 8:
        return False, "FEN board part must have 8 rows"
    if not re.fullmatch(r"[prnbqkPRNBQK1-8/]+", board_part):
        return False, "invalid board characters"
    if active not in ("w", "b"):
        return False, "FEN active color must be w or b"
    if not re.fullmatch(r"[KQkq-]{1,4}", castle):
        return False, "invalid castling field"
    if not re.fullmatch(r"(-|[a-h][36])", ep):
        return False, "invalid en-passant field"
    if not half.isdigit() or not full.isdigit():
        return False, "halfmove/fullmove must be integers"
    return True, "ok (basic check)"


class ChessEngine:
    """Thread-safe Stockfish wrapper with LRU cache."""

    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._engine_path: Optional[str] = None
        self._available = False
        self._init_engine()

    def _init_engine(self):
        if not HAS_CHESS:
            logger.warning(
                "python-chess not installed; engine will use material fallback only"
            )
            return

        cfg_path = getattr(settings, "stockfish_path", "stockfish")
        resolved = shutil.which(cfg_path) or (
            cfg_path if __import__("pathlib").Path(cfg_path).exists() else None
        )
        if resolved is None:

            for candidate in [
                "stockfish",
                "/usr/games/stockfish",
                "/usr/local/bin/stockfish",
                "/opt/homebrew/bin/stockfish",
            ]:
                if (
                    shutil.which(candidate)
                    or __import__("pathlib").Path(candidate).exists()
                ):
                    resolved = shutil.which(candidate) or candidate
                    break

        if resolved is None:
            logger.info(
                "Stockfish binary not found (STOCKFISH_PATH=%s); using material fallback",
                cfg_path,
            )
            return

        try:

            try:
                self._engine = chess.engine.SimpleEngine.popen_uci(resolved, timeout=5)
            except TypeError:

                self._engine = chess.engine.SimpleEngine.popen_uci(resolved)
            self._engine_path = resolved
            try:
                self._engine.configure(
                    {
                        "Threads": getattr(settings, "engine_threads", 1),
                        "Hash": getattr(settings, "engine_hash_mb", 64),
                    }
                )
            except Exception as e:
                logger.warning("Could not configure Stockfish: %s", e)
            self._available = True
            logger.info("Stockfish engine initialized at %s", resolved)
            atexit.register(self.close)
        except Exception as e:
            logger.warning(
                "Failed to start Stockfish at %s: %s; falling back to material eval",
                resolved,
                e,
            )
            self._engine = None
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and self._engine is not None

    def close(self):
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.quit()
                except Exception:
                    pass
                self._engine = None
                self._available = False

    def _evaluate_with_engine(self, fen: str) -> dict:
        """Internal engine eval; caller must hold lock."""
        if not self.is_available or not HAS_CHESS:
            raise RuntimeError("Engine not available")
        board = chess.Board(fen)
        limit = chess.engine.Limit(
            depth=getattr(settings, "engine_depth", 15),
            time=getattr(settings, "engine_timeout", 0.15),
        )
        info = self._engine.analyse(board, limit)
        score = info.get("score")
        pv = info.get("pv")
        depth = info.get("depth", getattr(settings, "engine_depth", 15))

        cp = None
        mate = None
        wdl = None
        if score is not None:

            try:

                w_score = score.white()
                if w_score.is_mate():
                    mate = w_score.mate()
                else:
                    cp = w_score.score()
            except Exception:

                try:
                    if score.is_mate():
                        mate = score.mate()
                    else:
                        cp = score.score()
                except Exception:
                    cp = None

            try:
                wdl_val = score.wdl(model="sf")
                if wdl_val is not None:

                    wdl = (
                        wdl_val.white().expectation()
                        if hasattr(wdl_val.white(), "expectation")
                        else None
                    )
            except Exception:
                wdl = None

        pv_san = None
        pv_uci = None
        if pv:
            try:

                pv_uci = pv[0].uci() if pv else None

                board_copy = chess.Board(fen)
                pv_san = board_copy.san(pv[0]) if pv else None
            except Exception:
                pass

        return {
            "cp": cp,
            "mate": mate,
            "pv": pv_uci,
            "pv_san": pv_san,
            "wdl": wdl,
            "depth": depth,
            "is_estimated": False,
            "fen": fen,
        }

    @lru_cache(maxsize=4096)
    def _cached_eval(self, fen: str) -> dict:
        """LRU-cached eval. Key is FEN string (normalized)."""
        valid, reason = fen_is_valid(fen)
        if not valid:
            return {
                "cp": None,
                "mate": None,
                "pv": None,
                "pv_san": None,
                "wdl": None,
                "depth": 0,
                "is_estimated": True,
                "error": f"invalid FEN: {reason }",
                "fen": fen,
            }

        if self.is_available:
            try:
                with self._lock:
                    return self._evaluate_with_engine(fen)
            except Exception as e:
                logger.warning(
                    "Engine eval failed for %s: %s; falling back", fen[:40], e
                )

                try:
                    self._available = False
                except Exception:
                    pass

        cp = _material_eval_fen(fen)
        mate = None
        if HAS_CHESS:
            try:
                board = chess.Board(fen)
                if board.is_checkmate():

                    mate = -1 if board.turn == chess.WHITE else 1
                elif board.is_stalemate():
                    cp = 0
            except Exception:
                pass
        return {
            "cp": cp,
            "mate": mate,
            "pv": None,
            "pv_san": None,
            "wdl": None,
            "depth": 0,
            "is_estimated": True,
            "fen": fen,
        }

    def evaluate_fen(self, fen: str) -> dict:
        """Public API: evaluate a FEN position.

        Returns dict with keys: cp, mate, pv, pv_san, wdl, depth, is_estimated, fen, error?
        Copies the cached dict to avoid mutation poisoning.
        """
        if not isinstance(fen, str):
            return {
                "cp": None,
                "mate": None,
                "pv": None,
                "pv_san": None,
                "wdl": None,
                "depth": 0,
                "error": "FEN must be string",
                "is_estimated": True,
                "fen": str(fen),
            }
        fen = fen.strip()

        fen = " ".join(fen.split())

        result = self._cached_eval(fen)

        return dict(result)

    def cache_clear(self):
        """Clear LRU cache (call when settings change)."""
        try:
            self._cached_eval.cache_clear()
        except Exception:
            pass

    def evaluate_position(self, board: "chess.Board") -> dict:
        """Evaluate a python-chess Board object."""
        if not HAS_CHESS:
            return {
                "cp": None,
                "mate": None,
                "pv": None,
                "is_estimated": True,
                "error": "python-chess not installed",
            }
        return self.evaluate_fen(board.fen())

    def get_best_move(self, fen: str) -> Optional[str]:
        """Return best move UCI for a FEN, or None."""
        result = self.evaluate_fen(fen)
        return result.get("pv")

    def analyze_game(self, pgn_text: str, max_ply: int = 60) -> list[dict]:
        """Analyze a PGN game move-by-move.

        Returns list of per-ply dicts: {ply, move_san, move_uci, fen_before, fen_after, eval_before, eval_after, cp_loss, classification}
        Limited to max_ply to bound compute (80 ply *0.15s=12s worst without cache).
        """
        if not HAS_CHESS:
            return [{"error": "python-chess not installed", "ply": 0}]

        import io

        try:
            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                return [{"error": "invalid PGN", "ply": 0}]
        except Exception as e:
            return [{"error": f"PGN parse failed: {e }", "ply": 0}]

        board = game.board()
        results = []
        ply = 0
        prev_eval = self.evaluate_fen(board.fen())

        for move in game.mainline_moves():
            if ply >= max_ply:
                break
            fen_before = board.fen()
            san = board.san(move)
            uci = move.uci()
            board.push(move)
            fen_after = board.fen()

            eval_after = self.evaluate_fen(fen_after)

            cp_before = prev_eval.get("cp")
            cp_after = eval_after.get("cp")

            if prev_eval.get("mate") is not None:
                cp_before = 10000 if prev_eval["mate"] > 0 else -10000
            if eval_after.get("mate") is not None:
                cp_after = 10000 if eval_after["mate"] > 0 else -10000

            cp_loss = None
            if cp_before is not None and cp_after is not None:

                is_white_move = ply % 2 == 0
                if is_white_move:
                    cp_loss = cp_before - cp_after
                else:
                    cp_loss = cp_after - cp_before

                if cp_loss is not None and cp_loss < 0:
                    cp_loss = 0

            classification = classify_move(cp_loss)

            results.append(
                {
                    "ply": ply + 1,
                    "move_san": san,
                    "move_uci": uci,
                    "fen_before": fen_before,
                    "fen_after": fen_after,
                    "eval_before": prev_eval,
                    "eval_after": eval_after,
                    "cp_loss": cp_loss,
                    "classification": classification,
                }
            )
            prev_eval = eval_after
            ply += 1

        return results


_engine_instance: Optional[ChessEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> ChessEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ChessEngine()
    return _engine_instance


def evaluate_fen(fen: str) -> dict:
    """Convenience function."""
    return get_engine().evaluate_fen(fen)
