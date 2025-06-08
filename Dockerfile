FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

# Install Poetry
RUN pip install poetry

WORKDIR /app

# Copy Poetry files
COPY chat/pyproject.toml chat/poetry.lock* /app/chat/

# Install dependencies with Poetry
WORKDIR /app/chat
RUN poetry install --no-root

# Copy the rest of the application
COPY ./chat /app/chat/

# Copy static files to Streamlit's static directory
COPY chat/static/js/*.js /usr/local/lib/python3.13/site-packages/streamlit/static/static/js/
COPY chat/static/img/ /usr/local/lib/python3.13/site-packages/streamlit/static/static/img/

# Run Streamlit with Poetry
CMD ["poetry", "run", "streamlit", "run", "app.py"]