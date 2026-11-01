# Conteneur Cloud Run. Image Python 3.11 et environnement verrouille par uv.lock.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Les versions Python proviennent du fichier uv.lock genere localement.
RUN pip install --no-cache-dir uv==0.11.7
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Les scripts de test, .env et donnees reelles sont exclus par .dockerignore.
COPY . .

# Cloud Run fournit le port via PORT. Ne JAMAIS exposer un mode auth bypass.
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn autoclaim_api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
