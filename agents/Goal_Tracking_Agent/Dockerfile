FROM python:3.12-slim

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[" && pip install --no-cache-dir .

COPY app/ ./app/

RUN chown -R appuser:appgroup /app
USER appuser

# Cloud Run sets PORT; default to 8080 for local runs
ENV PORT=8080
EXPOSE $PORT

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"]
