from utils.chess_engine import fen_is_valid, classify_move, _material_eval_fen

def test_fen_valid_start():
    ok, _ = fen_is_valid("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert ok

def test_fen_invalid_no_kings():
    ok, msg = fen_is_valid("8/8/8/8/8/8/8/8 w - - 0 1")
    assert not ok

def test_fen_invalid_svg():
    ok, _ = fen_is_valid("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR<svg> w KQkq - 0 1")
    assert not ok

def test_fen_too_long():
    ok, _ = fen_is_valid(" ".join(["a"]*300))
    assert not ok

def test_classify():
    assert classify_move(400) == "blunder"
    assert classify_move(150) == "mistake"
    assert classify_move(60) == "inaccuracy"
    assert classify_move(10) == "good"
    assert classify_move(None) == "unknown"

def test_material():

    cp = _material_eval_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert cp == 0

    cp2 = _material_eval_fen("4k3/8/8/3Q4/8/8/8/4K3 w - - 0 1")
    assert cp2 == 900
