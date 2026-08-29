# ChessMate

ChessMate is an AI-powered chess coaching tool designed to help players of all levels improve their chess skills. Whether you're a beginner looking to learn the basics or an advanced player aiming to refine your strategies, ChessMate provides personalized insights by analyzing your games, identifying mistakes, suggesting optimal moves, and offering tailored practice puzzles. With an interactive chessboard and a modern tech stack, ChessMate makes chess improvement engaging and accessible.

<p align="center">
  <img src="img/app.png">
</p>

## Features

**Game Analysis**: Get detailed feedback on your games, pinpointing errors and inaccuracies with clear explanations of what went wrong and how to improve.

**Best Move Suggestions**: Discover the strongest moves played in your games and receive recommendations for optimal plays in key positions.

**Practice Puzzles**: Solve custom chess puzzles generated from real game positions, provided in FEN notation to enhance your tactical skills — all puzzles are server-side validated via `python-chess`/`Stockfish`, never hallucinated.

**Study Material**: Explore similar games from a vast database to deepen your understanding of specific openings and strategies.

**Interactive Chessboard**: Visualize and interact with chess positions directly in the app using a draggable chessboard interface with FEN import/export and engine evaluation.

**Game Review Studio** (new): Move-by-move branching analysis with Stockfish truth layer, blunder/mistake/inaccuracy taxonomy and `+0.3` centipawn loss.

**Puzzle Trainer + SRS** (new): Deterministic puzzles with spaced-repetition (`interval*2`, 1 day → 60 days) and `next_due` scheduling.

## RAG Diagram

<p align="center">
  <img src="img/chess_assistant_app_diagram.png">
</p>

## Technologies Used

ChessMate is built with a powerful and modern tech stack:

**Streamlit**: A Python framework for creating the interactive web application interface.

**PostgreSQL**: A robust relational database to store conversation history and user feedback (`ThreadedConnectionPool`, indexes on `timestamp`/`relevance`).

**Elasticsearch**: A search engine for quickly retrieving relevant chess games based on moves and openings (now `opening:text + keyword`, `elo:integer`, `helpers.bulk` + alias swap).

**OpenAI API**: Leverages advanced language models to generate insightful chess analysis and responses (streaming, `system`/`user` split, sampled `20%` relevance eval).

**Chess Engine**: `python-chess` + Stockfish sidecar (optional, graceful material fallback, LRU `4096` FEN cache).

**Chessboard.js**: A JavaScript library for rendering an interactive chessboard within the app.

**Docker**: Containerizes the application and its dependencies for easy deployment and scalability.

**Grafana**: Used for monitoring (`postgres:16-alpine`, `grafana:11.2.0`, `WHERE $__timeFilter(timestamp)`).

## Setup and Installation

Follow these steps to set up ChessMate locally:

**Steps**

- **Clone the Repository**
``` bash
git clone https://github.com/yourusername/ChessMate.git
cd ChessMate
```

- **Set Up Environment Variables**
Create a `.env` file in the root directory. See `.env.example` for all options:
``` env
OPENAI_API_KEY=your_openai_api_key
POSTGRES_DB=chess_assistant
POSTGRES_USER=chess_assistant
POSTGRES_PASSWORD=CHANGE_ME_32_char_random
POSTGRES_PORT=5432
ELASTIC_URL=http://elasticsearch:9200
ELASTIC_URL_LOCAL=http://elasticsearch:9200
INDEX_NAME=chess-rag
STREAMLIT_PORT=8501
STOCKFISH_PATH=/usr/games/stockfish
EVAL_SAMPLE_RATE=0.2
GRAFANA_ADMIN_PASSWORD=CHANGE_ME_strong_grafana_pwd
```
Replace passwords with strong random values (`openssl rand -base64 24`).

- **Build and Run Docker Containers**
``` bash
docker compose up --build
# or: docker-compose up --build
```
This will start the Elasticsearch, PostgreSQL, and ChessMate application services (with healthchecks, `restart: unless-stopped`).

- **Initialize the Database and Load Chess Data** 
Once the containers are running, initialize the database and load chess games into Elasticsearch (from project root `data/lichess_db.pgn`):
``` bash
docker exec -it chess_assistant_app poetry run python utils/setup.py
# or inside chat/: poetry run python utils/setup.py
```
This script streams `chess.pgn.read_game`, indexes via `helpers.bulk(500)` with alias `chess-rag` → `chess-rag-vYYYYMMDDHHMMSS`.

- **Access the Application**
Open your browser and navigate to `http://localhost:8501` to start using ChessMate.

## Usage

ChessMate is intuitive and easy to use:

1. Start the App: After setup, access the web interface at http://localhost:8501.

2. Ask Questions: Enter chess-related questions or positions in the **Chat** tab (e.g., "Analyze my last game" or "What’s the best move here?"). Toggle **Use in chat** under the board to include the current FEN (validated server-side, engine `+0.32`).

3. Import Games: In the sidebar **Import Game**, paste PGN or upload a `.pgn` file (10 MB limit). Select a game, then use **Game Review** tab for move-by-move analysis (≤60 ply, ~9 s worst, cached) or **Use middle position** to ask about it.

4. Puzzles: Solve in the **Puzzles** tab – every puzzle FEN is `board.is_valid()` + `is_legal` checked; streak uses `interval*2` SRS.

5. Interact with the Chessboard: Drag pieces (`sparePieces:true`), **Set FEN**, **Flip**/**Copy FEN**; engine shows `Mate in 1` or `+0.5`.

6. Provide Feedback: Rate responses with 👍 (`1`) / 👎 (`-1`) to help refine the system (fixed inversion + `key=fb_*`).

### Monitoring

<p align="center">
  <img src="img/grafana_dashboard.png">
</p>

Provisioned via `monitoring/grafana/provisioning/` (`datasource.yml` + `dashboard.yml`). Dashboard now uses `WHERE $__timeFilter(timestamp)` for all time-series, `COALESCE` for empty feedback, and `total_time` vs `response_time`.

### Development

``` bash
# lint + type
make lint
# tests (requires pytest, free)
make test
# re-lock deps after pyproject change
make lock
```

See `chat/README.md` + `.env.example` for full env list (`PGN_PATH`, `MAX_INDEX_DOCS`, `BULK_CHUNK_SIZE`, `REDIS_URL`, `APP_ENV`).
