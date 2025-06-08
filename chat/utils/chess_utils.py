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
</head>
<body>
    <div id="board" style="width: 400px"></div>
    <input type="text" id="customPosition" placeholder="Enter chess position">
    <button id="customB">Set position</button>
    <button id="startPositionBtn">Start Position</button>

    <script src="https://code.jquery.com/jquery-3.5.1.min.js"
            integrity="sha384-ZvpUoO/+PpLXR1lu4jmpXWu80pZlYUAfxl5NsBMWOEPSjUn/6Z/hRTt8+pR6L4N2"
            crossorigin="anonymous"></script>
    <script src="/static/js/chessboard-1.0.0.js"></script>

    <script>
        // Ensure Chessboard is defined before initializing
        if (typeof Chessboard === 'undefined') {
            console.error('Chessboard library not loaded');
        } else {
            var board = Chessboard('board', {
                draggable: true,
                position: 'start',
                onSnapEnd: onSnapEnd,
                dropOffBoard: 'trash',
                sparePieces: true
            });

            $('#customB').on('click', setCustomPosition);
            $('#startPositionBtn').on('click', setStartPosition);

            function setCustomPosition() {
                const customPosition = document.getElementById('customPosition').value;
                console.log('Setting custom position:', customPosition);
                board.position(customPosition);
            }

            function setStartPosition() {
                console.log('Setting start position');
                board.position('start');
            }

            function onSnapEnd() {
                board.position(board.fen());
            }
        }
    </script>
</body>
</html>
"""