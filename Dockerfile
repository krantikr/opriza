# Backend image for the AI Sales Quotation Copilot.
#
# Runs the FastAPI app on a long-lived process (not serverless), so the full
# ingest+LLM cycle is never cut off by a function timeout, and WeasyPrint's
# native stack (Pango / Cairo / GDK-Pixbuf) is present so PDF generation works
# rather than silently degrading.
FROM python:3.12-slim

# WeasyPrint system libraries. Without these the PDF attachment feature falls
# back to disabled; with them it renders. libpq is for psycopg (Postgres).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        libpq5 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so the layer caches across code-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The app runs from the repo root: alembic's script_location is
# backend/migrations relative to here, and the `ai` package imports from root.
COPY . .

# The project is not pip-installed (requirements.txt is exported with
# --no-emit-project), so the import paths come from PYTHONPATH alone:
#   /app          -> the `ai` package and alembic config
#   /app/backend  -> makes `app.main` importable, the same as pyproject's
#                    pythonpath + the test harness do locally.
ENV PYTHONPATH=/app:/app/backend
ENV PORT=8000
EXPOSE 8000

# Render provides $PORT. Run migrations, then serve. A failed migration stops
# the boot rather than serving against a stale schema.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
