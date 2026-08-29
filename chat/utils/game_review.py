import logging
from typing import Optional

try:
    import chess
    import chess.pgn

    HAS_CHESS = True
except ImportError:
    HAS_CHESS = False
    chess = None

from utils.chess_engine import get_engine, classify_move, fen_is_valid

logger = logging.getLogger(__name__)


def analyze_pgn(pgn_text: str, max_ply: int = 60, progress_callback=None) -> dict:
    """Analyze a PGN game move-by-move.

    Returns dict:
      {
        "ok": bool,
        "error": str|None,
        "headers": dict,
        "ply_count": int,
        "moves": [ {ply, move_san, move_uci, fen_before, fen_after, eval_before, eval_after, cp_loss, classification, is_estimated} ],
        "summary": {blunder, mistake, inaccuracy, good counts, avg_cp_loss, biggest_blunder}
      }
    progress_callback: callable(ply_done, ply_total) for UI updates.
    """
    if not HAS_CHESS:
        return {"ok": False, "error": "python-chess not installed", "moves": []}
    if not pgn_text or not pgn_text.strip():
        return {"ok": False, "error": "empty PGN", "moves": []}

    import io

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception as e:
        return {"ok": False, "error": f"PGN parse failed: {e }", "moves": []}
    if game is None:
        return {"ok": False, "error": "invalid PGN (no game found)", "moves": []}

    headers = dict(game.headers)

    total_ply = 0
    try:
        total_ply = sum(1 for _ in game.mainline_moves())
    except Exception:
        total_ply = 0
    total_ply = min(total_ply, max_ply)

    engine = get_engine()
    board = game.board()
    moves = []
    ply = 0

    try:
        prev_eval = engine.evaluate_fen(board.fen())
    except Exception as e:
        logger.warning("Initial eval failed: %s", e)
        prev_eval = {"cp": 0, "mate": None, "is_estimated": True}

    blunders = mistakes = inaccuracies = goods = 0
    total_loss = 0
    counted = 0
    biggest = None

    for move in game.mainline_moves():
        if ply >= max_ply:
            break
        fen_before = board.fen()
        try:
            san = board.san(move)
        except Exception:
            san = move.uci()
        uci = move.uci()
        board.push(move)
        fen_after = board.fen()

        try:
            eval_after = engine.evaluate_fen(fen_after)
        except Exception as e:
            logger.warning("Eval failed ply %d: %s", ply + 1, e)
            eval_after = {"cp": None, "mate": None, "is_estimated": True}

        cp_before = prev_eval.get("cp")
        cp_after = eval_after.get("cp")
        mate_before = prev_eval.get("mate")
        mate_after = eval_after.get("mate")
        if mate_before is not None:
            cp_before = 10000 if mate_before > 0 else -10000
        if mate_after is not None:
            cp_after = 10000 if mate_after > 0 else -10000

        cp_loss = None
        if cp_before is not None and cp_after is not None:
            is_white_move = ply % 2 == 0
            if is_white_move:
                cp_loss = cp_before - cp_after
            else:
                cp_loss = cp_after - cp_before
            if cp_loss is not None and cp_loss < 0:
                cp_loss = 0

            if cp_loss is not None and cp_loss > 10000:
                cp_loss = 10000

        classification = classify_move(cp_loss)

        if classification == "blunder":
            blunders += 1
        elif classification == "mistake":
            mistakes += 1
        elif classification == "inaccuracy":
            inaccuracies += 1
        elif classification == "good":
            goods += 1

        if cp_loss is not None:
            total_loss += cp_loss
            counted += 1
            if biggest is None or cp_loss > biggest[0]:
                biggest = (cp_loss, ply + 1, san)

        moves.append(
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
                "is_estimated": eval_after.get("is_estimated", False),
            }
        )

        prev_eval = eval_after
        ply += 1
        if progress_callback:
            try:
                progress_callback(ply, total_ply)
            except Exception:
                pass

    avg_loss = total_loss / counted if counted else 0

    summary = {
        "blunder": blunders,
        "mistake": mistakes,
        "inaccuracy": inaccuracies,
        "good": goods,
        "avg_cp_loss": round(avg_loss, 1),
        "biggest_blunder": (
            {"cp_loss": biggest[0], "ply": biggest[1], "move": biggest[2]}
            if biggest and biggest[0] >= 100
            else None
        ),
        "total_ply": ply,
        "is_estimated": any(m.get("is_estimated") for m in moves),
    }

    return {
        "ok": True,
        "headers": headers,
        "ply_count": ply,
        "moves": moves,
        "summary": summary,
        "start_fen": (
            chess.Board().fen()
            if HAS_CHESS
            else "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        ),
        "final_fen": board.fen(),
    }


def get_game_opening(pgn_text: str) -> str:
    """Quick helper to get opening name."""
    import io

    if not HAS_CHESS:
        return ""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game:
            return game.headers.get("Opening", "") or game.headers.get("ECO", "")
    except Exception:
        pass
    return ""


def fen_after_moves(
    moves_uci: list[str], start_fen: Optional[str] = None
) -> Optional[str]:
    """Compute FEN after applying a sequence of UCI moves."""
    if not HAS_CHESS:
        return None
    try:
        board = chess.Board(start_fen) if start_fen else chess.Board()
        for uci in moves_uci:
            move = chess.Move.from_uci(uci)
            if not board.is_legal(move):
                return None
            board.push(move)
        return board.fen()
    except Exception:
        return None
