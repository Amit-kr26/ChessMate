import streamlit as st
st.set_page_config(page_title="ChessMate", page_icon="♟️", layout="centered")
import streamlit.components.v1 as components
from utils import llm_utils, chess_utils, db_utils
import uuid, hashlib, html, json, logging
from datetime import timedelta

try:
    from utils.chess_engine import get_engine, fen_is_valid
    HAS_ENGINE = True
except Exception as e:
    logging.warning("engine: %s", e)
    HAS_ENGINE = False
    get_engine = None
    fen_is_valid = lambda x: (False, "")

try:
    from utils.import_utils import parse_pgn_text, validate_and_normalize_fen, parse_uploaded_pgn_file, fetch_lichess_games_pgn, fetch_chesscom_games, fetch_pgn_url
    HAS_IMPORT = True
except Exception:
    HAS_IMPORT = False
    fetch_lichess_games_pgn = fetch_chesscom_games = fetch_pgn_url = None

try:
    from utils.game_review import analyze_pgn
    HAS_REVIEW = True
except Exception:
    HAS_REVIEW = False

try:
    from utils.puzzle_engine import get_puzzle_store
    HAS_PUZZLE = True
except Exception:
    HAS_PUZZLE = False

try:
    from utils.cache_utils import is_rate_limited
    HAS_CACHE = True
except Exception:
    HAS_CACHE = False
    def is_rate_limited(k, limit_per_minute=None, window=60): return False

logger = logging.getLogger(__name__)

if "session_id" not in st.session_state: st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state: st.session_state.messages = []
if "feedback" not in st.session_state: st.session_state.feedback = {}
if "conversation_id" not in st.session_state: st.session_state.conversation_id = str(uuid.uuid4())
if "current_fen" not in st.session_state: st.session_state.current_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
if "use_board_context" not in st.session_state: st.session_state.use_board_context = False
if "imported_games" not in st.session_state: st.session_state.imported_games = []
if "selected_game_idx" not in st.session_state: st.session_state.selected_game_idx = 0
if "puzzle_current" not in st.session_state: st.session_state.puzzle_current = None
if "review_result" not in st.session_state: st.session_state.review_result = None

with st.sidebar:
    st.header("Study section")
    components.html(chess_utils.chess_board, height=420, scrolling=False)
    fen_input = st.text_input("FEN", value=st.session_state.current_fen, label_visibility="collapsed", placeholder="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Apply FEN", use_container_width=True):
            r = validate_and_normalize_fen(fen_input) if HAS_IMPORT else {"valid":False}
            if r.get("valid"):
                st.session_state.current_fen = r["fen"]
                st.success("Applied")
            else:
                st.error(r.get("error","invalid"))
    with c2:
        st.checkbox("Use in chat", key="use_board_context")
    st.code(st.session_state.current_fen, language="text")
    if HAS_ENGINE:
        try:
            ev = get_engine().evaluate_fen(st.session_state.current_fen)
            if not ev.get("error"):
                if ev.get("mate") is not None:
                    st.caption(f"Mate in {abs(ev['mate'])}")
                elif ev.get("cp") is not None:
                    st.caption(f"Eval {ev['cp']/100:+.2f}")
        except Exception: pass
    with st.expander("Load game"):
        ptxt = st.text_area("Paste PGN", height=70, placeholder="1. e4 e5…", key="pgn_paste")
        up = st.file_uploader("Upload PGN", type=["pgn","txt"], label_visibility="collapsed")
        if st.button("Parse", use_container_width=True):
            if is_rate_limited(st.session_state.session_id+":import", limit_per_minute=20):
                st.error("Wait")
            else:
                games, errs = [], []
                if up is not None:
                    games, errs = parse_uploaded_pgn_file(up.getvalue(), up.name, 10)
                elif ptxt.strip():
                    if len(ptxt)>500_000: st.error("Too large")
                    else:
                        games = parse_pgn_text(ptxt, 5)
                        errs = [g["error"] for g in games if not g.get("valid")]
                if errs: st.error(errs[0][:200])
                valid=[g for g in games if g.get("valid")]
                if valid:
                    st.session_state.imported_games=valid; st.session_state.selected_game_idx=0; st.success(f"{len(valid)} game(s)")
        st.divider()
        plat = st.selectbox("Fetch from", ["Lichess","Chess.com"], key="plat2")
        user = st.text_input("Username", placeholder="hikaru", key="user2")
        if st.button("Fetch", use_container_width=True):
            if not user.strip(): st.warning("Enter username")
            elif is_rate_limited(st.session_state.session_id+":fetch", limit_per_minute=10): st.error("Wait")
            else:
                with st.spinner("Fetching..."):
                    try:
                        if plat=="Lichess": games,errs=fetch_lichess_games_pgn(user.strip(), max_games=5)
                        else: games,errs=fetch_chesscom_games(user.strip(), max_games=5)
                        if errs: st.warning(errs[0][:200])
                        valid=[g for g in games if g.get("valid")]
                        if valid: st.session_state.imported_games=valid; st.session_state.selected_game_idx=0; st.success(f"Fetched {len(valid)}")
                        else: st.error("No games")
                    except Exception as e: st.error(str(e)[:200])
        purl = st.text_input("PGN URL", placeholder="https://lichess.org/abc123", key="purl2")
        if st.button("Fetch URL", use_container_width=True):
            if not purl.strip(): st.warning("Enter URL")
            else:
                with st.spinner("Fetching..."):
                    games,errs=fetch_pgn_url(purl.strip(), max_games=5)
                    if errs: st.warning(errs[0][:200])
                    valid=[g for g in games if g.get("valid")]
                    if valid: st.session_state.imported_games=valid; st.session_state.selected_game_idx=0; st.success(f"{len(valid)}")
    if st.session_state.imported_games:
        opts=[f"{i+1}. {g.get('white','?')}–{g.get('black','?')} {g.get('result','*')}" for i,g in enumerate(st.session_state.imported_games)]
        sel=st.selectbox("Game", range(len(opts)), format_func=lambda i: opts[i], key="sel2")
        st.session_state.selected_game_idx=sel
        g=st.session_state.imported_games[sel]
        st.caption(f"{g.get('opening','')} • {len(g.get('moves_san',[]))} ply")
        if st.button("Use position", use_container_width=True):
            try:
                from utils.import_utils import extract_fens_from_game
                f=extract_fens_from_game(g.get("pgn_text",""),"middle")
                if f: st.session_state.current_fen=f[0]; st.session_state.use_board_context=True; st.success("Set")
            except Exception: pass

@st.cache_data(ttl=timedelta(hours=1), max_entries=100)
def rag_cached(prompt, fen_context=None):
    return llm_utils.rag(prompt, fen_context=fen_context)

def hash_text(t): return hashlib.sha256(t.encode()).hexdigest()[:16]

st.title("💬 ChessMate - A Chess Teacher")
st.caption("Ask about chess, review your games, or solve puzzles.")

chat_tab, review_tab, puzzle_tab = st.tabs(["Chat", "Review", "Puzzles"])

with chat_tab:
    box = st.container()
    if not st.session_state.messages:
        box.info("No messages yet. Try *Analyze my French Defense* or drag the board.")
    for m in st.session_state.messages[-30:]:
        box.chat_message(m["role"]).write(m["content"])
    def save_fb(**kw):
        sid=st.session_state.session_id
        st.session_state.feedback.setdefault(sid,[]).append(kw)
        try: db_utils.save_feedback(kw["conversation_id"], kw["rating"])
        except Exception as e: st.toast(str(e))
        box.success("Thanks!")
    if prompt := st.chat_input("Ask about chess…"):
        if not prompt.strip(): st.warning("Enter question"); st.stop()
        if len(prompt)>500: prompt=prompt[:500]
        if is_rate_limited(st.session_state.session_id): st.error("Wait 60s"); st.stop()
        st.session_state.messages.append({"role":"user","content":prompt})
        fen_ctx = st.session_state.current_fen if st.session_state.use_board_context else None
        if fen_ctx and HAS_ENGINE and not fen_is_valid(fen_ctx)[0]: fen_ctx=None
        if len(st.session_state.messages)>30: st.session_state.messages=st.session_state.messages[-30:]
        for m in st.session_state.messages[-30:]:
            box.chat_message(m["role"]).write(m["content"])
        with st.status(f"Analyzing {prompt[:30]}…", expanded=False) as s:
            try:
                if st.session_state.get("use_streaming"):
                    import time as _ti, os as _os
                    t0=_ti.time()
                    res=llm_utils.elastic_search(prompt)
                    pr=llm_utils.build_prompt(prompt, res[:5], fen_context=fen_ctx)
                    ph=st.empty(); col=""
                    for ch in llm_utils.llm_stream(pr):
                        col+=ch; ph.markdown(col+"▌")
                    ph.markdown(col)
                    rt=_ti.time()-t0
                    try: sr=float(_os.getenv("EVAL_SAMPLE_RATE","0.2")); sr=max(0,min(1,sr))
                    except: sr=0.2
                    try: rel,expl,etok=llm_utils.evaluate_relevance(prompt,col,sample_rate=sr)
                    except: rel,expl,etok="UNKNOWN","",{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
                    ans={"answer":col,"response_time":rt,"total_time":rt,"relevance":rel,"relevance_explanation":expl,"model_used":getattr(llm_utils,"openai_model",""),"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"eval_prompt_tokens":etok.get("prompt_tokens",0),"eval_completion_tokens":etok.get("completion_tokens",0),"eval_total_tokens":etok.get("total_tokens",0),"prompt":pr if _os.getenv("LOG_PROMPT")=="1" else None}
                else:
                    ans=rag_cached(prompt, fen_context=fen_ctx)
                s.update(label="Done", state="complete")
            except Exception as e:
                s.update(label=str(e), state="error"); st.error(str(e)); ans=None
        if ans:
            txt=ans["answer"]
            st.session_state.messages.append({"role":"assistant","content":txt})
            box.chat_message("assistant").write(txt)
            try: db_utils.save_conversation(st.session_state.conversation_id, prompt, ans)
            except Exception: pass
            c1,c2,c3=box.columns([2,1,1])
            fid=hash_text(prompt+txt)
            c1.write("Rate:")
            c2.button("👎", key=f"dn_{fid}", on_click=save_fb, kwargs={"conversation_id":st.session_state.conversation_id,"rating":-1})
            c3.button("👍", key=f"up_{fid}", on_click=save_fb, kwargs={"conversation_id":st.session_state.conversation_id,"rating":1})
            st.session_state.conversation_id=str(uuid.uuid4())

with review_tab:
    st.subheader("Game Review")
    st.caption("Engine checks every move.")
    src=""
    if st.session_state.imported_games:
        g=st.session_state.imported_games[st.session_state.selected_game_idx]
        src=g.get("pgn_text","")
        st.text_area("PGN", value=src, height=80, disabled=True)
    else:
        src=st.text_area("Paste PGN", height=100, placeholder="1. e4 e5…")
    maxp=st.slider("Max ply",10,120,60)
    if st.button("Analyze", type="primary", disabled=not src.strip()):
        if is_rate_limited(st.session_state.session_id+":review",limit_per_minute=10): st.error("Wait")
        else:
            prog=st.progress(0); stat=st.status("Analyzing…", expanded=True)
            def cb(d,t): prog.progress(d/t if t else 0)
            try:
                res=analyze_pgn(src, max_ply=maxp, progress_callback=cb) if HAS_REVIEW else {"ok":False,"error":"no engine"}
                st.session_state.review_result=res
                prog.progress(1.0); stat.update(label=f"{res.get('ply_count',0)} ply", state="complete" if res.get("ok") else "error")
            except Exception as e: stat.update(label=str(e), state="error")
    res=st.session_state.get("review_result")
    if res and res.get("ok"):
        s=res["summary"]
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Blunders", s["blunder"]); c2.metric("Mistakes", s["mistake"]); c3.metric("Inaccuracies", s["inaccuracy"]); c4.metric("Avg loss", s["avg_cp_loss"])
        for m in res["moves"]:
            e=m["eval_after"]; txt=f"Mate {abs(e['mate'])}" if e.get("mate") is not None else f"{e['cp']/100:+.2f}" if e.get("cp") is not None else "?"
            a,b,c,_=st.columns([1,2,2,2])
            a.write(f"{m['ply']}."); b.markdown(f"**{html.escape(m['move_san'])}** {m['classification']}"); c.write(f"loss {m['cp_loss'] or 0}"); c.write(f"{txt}")
        st.download_button("Download JSON", data=json.dumps(res,indent=2,default=str), file_name="analysis.json")
        if st.button("Summarize"):
            try:
                txt=" ".join(f"{m['ply']}.{m['move_san']}({m['classification']})" for m in res["moves"][:20])
                q=f"Summarize {res['headers'].get('White','?')} vs {res['headers'].get('Black','?')} {txt}"
                st.write(llm_utils.rag(q, fen_context=res["final_fen"])["answer"])
            except Exception as e: st.error(str(e))

with puzzle_tab:
    st.subheader("Verified Puzzles")
    st.caption("All FENs validated.")
    if not HAS_PUZZLE:
        st.error("Unavailable")
    else:
        store=get_puzzle_store()
        c1,c2,c3=st.columns([2,2,1])
        with c1: rv=st.slider("Rating",400,2500,1200, key="pr2")
        with c2: th=st.selectbox("Theme",["any","fork","pin","backRankMate"], key="pt2")
        with c3:
            if st.button("Next", use_container_width=True): st.session_state.puzzle_current=None
        if st.session_state.puzzle_current is None:
            mot=None if th=="any" else th
            p=store.get_next_puzzle(st.session_state.session_id, rating=rv)
            if mot and p and mot not in p.get("motifs",[]): 
                cand=store.list_puzzles(20, rv-200, rv+200, motif=mot)
                p=cand[0] if cand else p
            st.session_state.puzzle_current=p
        p=st.session_state.puzzle_current
        if not p: st.info("No puzzles")
        else:
            st.subheader(f"{html.escape(str(p['id']))} — {p.get('rating','?')}")
            st.code(p["fen"], language="text")
            st.caption(p.get("description",""))
            if st.button("Load on board"):
                st.session_state.current_fen=p["fen"]; st.success("Loaded")
            mv=st.text_input("UCI (e.g. e2e4)", placeholder="f3e5")
            b1,b2=st.columns(2)
            with b1:
                if st.button("Submit", type="primary"):
                    if not mv.strip(): st.warning("Enter move")
                    else:
                        r=store.check_solution(p["id"], [m.strip() for m in mv.split() if m.strip()])
                        if r.get("needs_more"): st.info(f"Need {' '.join(r['expected'])}")
                        elif r.get("correct"): st.success(f"Correct {' '.join(r['expected'])}"); store.record_attempt(p["id"], st.session_state.session_id, True)
                        else: st.error(f"Wrong {' '.join(r.get('expected',[]))}"); store.record_attempt(p["id"], st.session_state.session_id, False)
            with b2:
                if st.button("Show solution"): st.code(p.get("moves",""))
            st.caption(f"Due: {sum(1 for (i,s),d in store._next_due.items() if s==st.session_state.session_id and d<=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))} | Total {len(store._puzzles)}")

st.divider()
st.checkbox("Streaming", key="use_streaming")
