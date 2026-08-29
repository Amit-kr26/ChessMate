import logging
import json
import csv
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    import chess

    HAS_CHESS = True
except ImportError:
    HAS_CHESS = False
    chess = None

from utils.chess_engine import fen_is_valid, get_engine

logger = logging.getLogger(__name__)

STARTER_PUZZLES = [
    {
        "id": "mate1_001",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
        "moves": "f3e5",
        "solution": ["f3e5"],
        "rating": 800,
        "motifs": ["fork"],
        "description": "Knight fork",
    },
    {
        "id": "mate_in_1_001",
        "fen": "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
        "moves": "e1e8",
        "solution": ["e1e8"],
        "rating": 1200,
        "motifs": ["backRankMate"],
        "description": "Back rank mate in 1",
    },
    {
        "id": "tactic_001",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "moves": "c4f7",
        "solution": ["c4f7"],
        "rating": 1000,
        "motifs": ["fork", "capturingDefender"],
        "description": "Bxf7+ fork",
    },
    {
        "id": "mate_in_2_001",
        "fen": "r2qk2r/ppp2ppp/2n1bn2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 4 6",
        "moves": "f3g5 d7d5 e5d5",
        "solution": ["f3g5", "d7d5", "e5d5"],
        "rating": 1400,
        "motifs": ["pin", "discoveredAttack"],
        "description": "Tactic sequence",
    },
]


def _validate_puzzle(fen: str, moves: str) -> tuple[bool, str]:
    """Validate puzzle FEN and moves sequence."""
    valid, reason = fen_is_valid(fen)
    if not valid:
        return False, f"invalid FEN: {reason }"
    if not HAS_CHESS:
        return True, "ok (no chess)"
    try:
        board = chess.Board(fen)
        for uci in moves.split():
            if not uci:
                continue
            try:
                move = chess.Move.from_uci(uci)
            except Exception as e:
                return False, f"invalid UCI {uci }: {e }"
            if not board.is_legal(move):
                return False, f"illegal move {uci } in {fen }"
            board.push(move)
        return True, "ok"
    except Exception as e:
        return False, str(e)


class PuzzleStore:
    """In-memory puzzle store with optional Postgres backing."""

    def __init__(self):
        self._puzzles: dict[str, dict] = {}
        for p in STARTER_PUZZLES:
            self._puzzles[p["id"]] = p
        self._attempts: dict[tuple[str, str], dict] = {}
        self._next_due: dict[tuple[str, str], datetime] = {}

    def add_puzzle(self, puzzle: dict) -> bool:
        fen = puzzle.get("fen", "")
        moves = puzzle.get("moves", "")
        valid, reason = _validate_puzzle(fen, moves)
        if not valid:
            logger.warning("Reject puzzle %s: %s", puzzle.get("id"), reason)
            return False
        pid = puzzle.get("id") or str(uuid.uuid4())
        puzzle["id"] = pid

        if isinstance(moves, str):
            puzzle["solution"] = [m for m in moves.split() if m]
        self._puzzles[pid] = puzzle
        return True

    def import_csv(self, csv_path: str | Path, limit: int = 10000) -> int:
        """Import Lichess puzzle DB CSV (fields: PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags)."""
        path = Path(csv_path)
        if not path.exists():
            logger.info("Puzzle CSV not found at %s", path)
            return 0
        count = 0
        try:
            with open(path, newline="", encoding="utf-8") as f:

                sample = f.read(2048)
                f.seek(0)
                has_header = "PuzzleId" in sample or "FEN" in sample
                reader = csv.DictReader(f) if has_header else csv.reader(f)
                for row in reader:
                    if count >= limit:
                        break
                    try:
                        if isinstance(row, dict):

                            pid = (
                                row.get("PuzzleId")
                                or row.get("id")
                                or str(uuid.uuid4())
                            )
                            fen = row.get("FEN") or row.get("fen") or ""
                            moves = row.get("Moves") or row.get("moves") or ""
                            rating = int(row.get("Rating") or row.get("rating") or 1500)
                            themes = row.get("Themes") or row.get("motifs") or ""
                            if isinstance(themes, str):
                                motifs = [
                                    t.strip() for t in themes.split() if t.strip()
                                ]
                            else:
                                motifs = themes
                        else:

                            pid, fen, moves = row[0], row[1], row[2]
                            rating = int(row[3]) if len(row) > 3 else 1500
                            motifs = row[7].split() if len(row) > 7 else []
                        if not fen or not moves:
                            continue
                        valid, _ = _validate_puzzle(fen, moves)
                        if not valid:
                            continue
                        self._puzzles[pid] = {
                            "id": pid,
                            "fen": fen,
                            "moves": moves,
                            "solution": moves.split(),
                            "rating": rating,
                            "motifs": motifs,
                        }
                        count += 1
                    except Exception as e:
                        logger.debug("CSV row skip: %s", e)
                        continue
        except Exception as e:
            logger.warning("Puzzle import failed: %s", e)
            return count
        logger.info("Imported %d puzzles from %s", count, path)
        return count

    def get_puzzle(self, puzzle_id: str) -> Optional[dict]:
        return self._puzzles.get(puzzle_id)

    def list_puzzles(
        self,
        limit: int = 20,
        rating_min: int = 0,
        rating_max: int = 3000,
        motif: Optional[str] = None,
    ) -> list[dict]:
        out = []
        for p in self._puzzles.values():
            r = p.get("rating", 1500)
            if not (rating_min <= r <= rating_max):
                continue
            if motif and motif not in p.get("motifs", []):
                continue
            out.append(p)
            if len(out) >= limit:
                break
        return out

    def get_next_puzzle(self, session_id: str, rating: int = 1200) -> Optional[dict]:
        """Get next puzzle for a session, respecting SRS due dates."""
        now = datetime.now(timezone.utc)

        due = []
        for (pid, sid), due_date in self._next_due.items():
            if sid != session_id:
                continue
            if due_date <= now:
                p = self._puzzles.get(pid)
                if p:
                    due.append((due_date, p))
        if due:
            due.sort(key=lambda x: x[0])
            return due[0][1]

        seen = {pid for (pid, sid) in self._attempts if sid == session_id}
        candidates = [p for pid, p in self._puzzles.items() if pid not in seen]
        if not candidates:

            candidates = list(self._puzzles.values())

        candidates.sort(key=lambda p: abs(p.get("rating", 1500) - rating))
        return candidates[0] if candidates else None

    def check_solution(self, puzzle_id: str, attempted_moves: list[str]) -> dict:
        """Check if attempted UCI moves solve the puzzle.

        Supports single-move and multi-move sequences. Returns {correct, expected, is_checkmate}.
        """
        puzzle = self._puzzles.get(puzzle_id)
        if not puzzle:
            return {"correct": False, "error": "puzzle not found", "expected": []}
        expected = puzzle.get("solution") or puzzle.get("moves", "").split()

        exp = [m.strip() for m in expected if m.strip()]
        att = [m.strip() for m in attempted_moves if m.strip()]

        correct = (att == exp[: len(att)]) if att else False

        if HAS_CHESS and correct:
            try:
                board = chess.Board(puzzle["fen"])
                for uci in att:
                    move = chess.Move.from_uci(uci)
                    if not board.is_legal(move):
                        correct = False
                        break
                    board.push(move)
                is_mate = board.is_checkmate() if correct else False
            except Exception:
                is_mate = False
        else:
            is_mate = False

        if len(exp) > 1 and len(att) < len(exp):

            return {
                "correct": False,
                "partial": correct,
                "expected": exp,
                "is_checkmate": False,
                "needs_more": True,
            }
        return {"correct": correct, "expected": exp, "is_checkmate": is_mate}

    def record_attempt(self, puzzle_id: str, session_id: str, solved: bool) -> dict:
        """Record an attempt and update SRS interval."""
        now = datetime.now(timezone.utc)
        key = (puzzle_id, session_id)
        prev = self._attempts.get(
            key, {"attempts": 0, "interval_days": 0, "solved_count": 0}
        )
        attempts = prev["attempts"] + 1
        interval = prev.get("interval_days", 0)

        if solved:
            solved_count = prev.get("solved_count", 0) + 1

            if interval == 0:
                interval = 1
            else:
                interval = min(interval * 2 + random.randint(0, 1), 60)
        else:
            solved_count = 0
            interval = 0
            next_due = now + timedelta(hours=1)
            self._attempts[key] = {
                "attempts": attempts,
                "interval_days": interval,
                "solved_count": solved_count,
                "last_seen": now,
            }
            self._next_due[key] = next_due
            return {
                "attempts": attempts,
                "interval_days": interval,
                "next_due": next_due,
                "solved": solved,
            }

        next_due = now + timedelta(days=interval)
        self._attempts[key] = {
            "attempts": attempts,
            "interval_days": interval,
            "solved_count": solved_count,
            "last_seen": now,
        }
        self._next_due[key] = next_due
        return {
            "attempts": attempts,
            "interval_days": interval,
            "next_due": next_due,
            "solved": solved,
        }


_store: Optional[PuzzleStore] = None


def get_puzzle_store() -> PuzzleStore:
    global _store
    if _store is None:
        _store = PuzzleStore()

        default_csv = (
            Path(__file__).resolve().parents[2] / "data" / "lichess_puzzle.csv"
        )
        if default_csv.exists():
            _store.import_csv(default_csv, limit=5000)
    return _store
