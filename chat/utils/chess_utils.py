chess_board = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat and Chess</title>
    <link rel="stylesheet"
      href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css"
      integrity="sha384-q94+BZtLrkL1/ohfjR8c6L+A6qzNH9R2hBLwyoAfu3i/WCvQjzL2RQJ3uNHDISdU"
      crossorigin="anonymous">
    <style>
        /* Responsive sizing */
        #board { width: 100%; max-width: 400px; aspect-ratio: 1; margin: 0 auto; }
        .board-controls { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
        .board-row { display: flex; gap: 6px; }
        .board-row input { flex: 1; padding: 6px 8px; font-size: 12px; }
        .board-row button { padding: 6px 12px; cursor: pointer; font-size: 12px; }
        #fenDisplay { font-size: 11px; word-break: break-all; color: #555; margin-top: 6px; padding: 4px 6px; background: #f5f5f5; border-radius: 4px; max-width: 400px; }
        #statusMsg { font-size: 11px; margin-top: 4px; min-height: 14px; }
        .error { color: #c0392b; }
        .ok { color: #27ae60; }
    </style>
</head>
<body>
    <div id="board"></div>
    <div id="fenDisplay" title="Current FEN — copy to use with 'Analyze this position'">rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1</div>
    <div id="statusMsg"></div>
    <div class="board-controls">
        <div class="board-row">
            <input type="text" id="customPosition" placeholder="Paste FEN (e.g. rnbqkbnr/pppp... w KQkq - 0 1)" aria-label="FEN input">
            <button id="customB" aria-label="Set custom position">Set FEN</button>
        </div>
        <div class="board-row">
            <button id="startPositionBtn" aria-label="Reset to start position">Start Position</button>
            <button id="flipBtn" aria-label="Flip board">Flip Board</button>
            <button id="copyFenBtn" aria-label="Copy FEN to clipboard">Copy FEN</button>
        </div>
        <div class="board-row">
            <button id="undoBtn" aria-label="Undo last move">Undo</button>
            <button id="clearBtn" aria-label="Clear board">Clear</button>
        </div>
    </div>

    <script src="https://code.jquery.com/jquery-3.7.1.min.js"
            integrity="sha256-/JqT3SQfawRcv/BIHPThkBvs0OEvtFFmqPF/lYI/Cxo="
            crossorigin="anonymous"></script>
    <script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"
            crossorigin="anonymous"></script>
    <script>
        // Fallback if CDN fails – load local
        if (typeof jQuery === 'undefined') {
            document.write('<script src="/app/static/js/jquery-3.7.1.min.js"><\\/script>');
        }
        if (typeof Chessboard === 'undefined') {
            document.write('<script src="/app/static/js/chessboard-1.0.0.min.js"><\\/script>');
        }
    </script>
    <!-- Chess.js for move validation (loaded if available) -->
    <script>
        // Ensure Chessboard is defined before initializing
        if (typeof Chessboard === 'undefined') {
            console.error('Chessboard library not loaded');
            document.getElementById('statusMsg').textContent = 'Board failed to load.';
            document.getElementById('statusMsg').className = 'error';
        } else {
            var board = null;
            var lastFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
            var debounceTimer = null;

            function showStatus(msg, isError) {
                var el = document.getElementById('statusMsg');
                el.textContent = msg;
                el.className = isError ? 'error' : 'ok';
                if (!isError) setTimeout(function(){ if (el.textContent===msg) el.textContent=''; }, 3000);
            }

            function updateFenDisplay(fen) {
                lastFen = fen;
                document.getElementById('fenDisplay').textContent = fen;
                // Debounced postMessage to Streamlit parent
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(function(){
                    try {
                        // For Streamlit components.html iframe: post to parent
                        window.parent.postMessage({type: 'chessmate:fen', fen: fen}, '*');
                        // Also try Streamlit setComponentValue if available (custom component)
                        if (window.Streamlit && window.Streamlit.setComponentValue) {
                            window.Streamlit.setComponentValue(fen);
                        }
                    } catch(e) { console.warn('postMessage failed', e); }
                    // Persist to localStorage for app.py to poll via query params fallback
                    try { localStorage.setItem('chessmate:fen', fen); } catch(e){}
                }, 200);
            }

            function isValidFen(fen) {
                // Client-side lightweight validation (full check server-side via chess.Board)
                if (!fen || typeof fen !== 'string') return false;
                var parts = fen.trim().split(/\\s+/);
                if (parts.length !== 6) return false;
                var rows = parts[0].split('/');
                if (rows.length !== 8) return false;
                if (['w','b'].indexOf(parts[1]) === -1) return false;
                return true;
            }

            board = Chessboard('board', {
                draggable: true,
                position: 'start',
                onDrop: onDrop,
                onSnapEnd: onSnapEnd,
                dropOffBoard: 'trash',
                sparePieces: false,
                showNotation: true,
                pieceTheme: '/app/static/img/chesspieces/wikipedia/{piece}.png'
            });

            // Listen for position changes from spare pieces disabled; ensure valid
            function onDrop(source, target, piece, newPos, oldPos, orientation) {
                // Allow all drops; validation happens server-side. But prevent leaving kingless position silent
                // Chessboard.js doesn't validate chess rules; we just update FEN display
                // Returning undefined allows the move
            }

            function onSnapEnd() {
                try {
                    var fen = board.fen();
                    // Append active color, castling etc if board.fen() is partial (chessboard.js returns partial)
                    // chessboard.js fen() returns only piece placement; we need to reconstruct full FEN
                    // For now, keep as piece placement + default suffix; server will canonicalize
                    // If fen has spaces, it's already full; else append defaults
                    if (fen.split(' ').length === 1) {
                        // Try to preserve last full FEN's suffix
                        var suffix = lastFen.split(' ').slice(1).join(' ') || 'w KQkq - 0 1';
                        // Toggle turn based on move count heuristic: flip active color
                        var active = suffix.split(' ')[0] === 'w' ? 'b' : 'w';
                        var parts = suffix.split(' ');
                        parts[0] = active;
                        fen = fen + ' ' + parts.join(' ');
                    }
                    updateFenDisplay(fen);
                } catch(e) {
                    console.warn('onSnapEnd', e);
                }
            }

            function setCustomPosition() {
                var customPosition = document.getElementById('customPosition').value.trim();
                if (!customPosition) { showStatus('Enter a FEN first', true); return; }
                // Accept 'start' keyword
                if (customPosition.toLowerCase() === 'start') { setStartPosition(); return; }
                if (!isValidFen(customPosition)) {
                    showStatus('Invalid FEN: must have 6 fields (board active castling en-passant half full)', true);
                    return;
                }
                try {
                    board.position(customPosition);
                    updateFenDisplay(customPosition);
                    showStatus('Position set', false);
                } catch(e) {
                    showStatus('Failed to set: ' + e.message, true);
                }
            }

            function setStartPosition() {
                board.start();
                var startFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
                updateFenDisplay(startFen);
                showStatus('Start position', false);
            }

            // Bind buttons
            $('#customB').on('click', setCustomPosition);
            // Allow Enter in input
            document.getElementById('customPosition').addEventListener('keydown', function(e){ if(e.key==='Enter') setCustomPosition(); });
            $('#startPositionBtn').on('click', setStartPosition);
            $('#flipBtn').on('click', function(){ board.flip(); });
            $('#copyFenBtn').on('click', function(){
                var fen = lastFen;
                if (navigator.clipboard) navigator.clipboard.writeText(fen).then(function(){ showStatus('FEN copied', false); });
                else { prompt('Copy FEN:', fen); }
                // Also fill input for visibility
                document.getElementById('customPosition').value = fen;
            });
            $('#undoBtn').on('click', function(){
                // Simple: reset to previous? Chessboard has no history; we just inform
                showStatus('Undo: drag pieces back or set FEN', true);
            });
            $('#clearBtn').on('click', function(){
                // Use legal minimal position (kings present) instead of 8/8/8
                board.clear();
                var legalClear = '4k3/8/8/8/8/8/8/4K3 w - - 0 1';
                board.position(legalClear);
                updateFenDisplay(legalClear);
            });

            // Listen for messages from parent (Streamlit -> board)
            window.addEventListener('message', function(event){
                try {
                    var data = event.data;
                    if (data && data.type === 'chessmate:setFen' && data.fen) {
                        if (isValidFen(data.fen)) {
                            board.position(data.fen);
                            updateFenDisplay(data.fen);
                        }
                    }
                } catch(e){}
            });

            // Initial publish
            updateFenDisplay(lastFen);

            // Also respond to Streamlit's component ready protocol if present
            if (window.Streamlit) {
                window.Streamlit.setComponentReady();
                window.Streamlit.setFrameHeight(650);
            }
        }
    </script>
</body>
</html>
"""
