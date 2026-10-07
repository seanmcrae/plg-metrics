FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --extra dashboard --locked \
    && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"

RUN plg generate --out data/synthetic
EXPOSE 8501
CMD ["streamlit", "run", "src/plg/dashboard.py", "--server.address=0.0.0.0", "--", "--data", "data/synthetic"]
