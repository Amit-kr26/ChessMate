from utils.import_utils import parse_pgn_text, validate_and_normalize_fen, parse_uploaded_pgn_file

def test_parse_pgn_basic():
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
    games = parse_pgn_text(pgn, max_games=1)
    assert games
    assert games[0]["valid"]
    assert "e4" in games[0]["moves_san"]

def test_parse_pgn_guard():
    big = "e4 " * 200000
    games = parse_pgn_text(big)
    assert games[0].get("error") is not None

def test_fen_validate():
    res = validate_and_normalize_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert res["valid"]
    res2 = validate_and_normalize_fen("invalid fen")
    assert not res2["valid"]

def test_file_guard():
    data = b"x" * (10*1024*1024 + 1)
    games, errs = parse_uploaded_pgn_file(data, "big.pgn")
    assert "too large" in errs[0]
