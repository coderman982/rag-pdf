FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies from the project's own pyproject.toml. We install the
# declared dependencies rather than the project itself (`pip install .`): this
# is an application, not a library, and setuptools refuses to auto-discover a
# flat layout containing uploads/ and qdrant_storage/.
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY main.py data_loader.py vector_db.py custom_types.py settings.py streamlit_app.py ./

RUN mkdir -p /data/uploads

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]