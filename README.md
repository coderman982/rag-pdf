# RAG PDF

Upload a PDF, ingest it into Qdrant via an OpenAI embedding, then ask questions
about it. Ingestion and querying are driven by [Inngest](https://www.inngest.com)
workflows; the UI is Streamlit.

## Architecture

Four processes:

| Process       | Role                                             | Port |
| ------------- | ------------------------------------------------ | ---- |
| `api`         | FastAPI, serves the Inngest functions at `/api/inngest` | 8000 |
| `inngest`     | Executes the workflows triggered by events      | 8288 |
| `streamlit`   | The UI                                           | 8501 |
| `qdrant`      | Vector store                                     | 6333 |

The flow:

1. Streamlit writes the PDF to `UPLOADS_DIR` and sends `rag/ingest_pdf`.
2. Inngest calls back into `api`, which chunks the PDF, embeds it, and upserts to Qdrant.
3. Streamlit sends `rag/query_pdf_ai` and polls the Inngest REST API until the
   function finishes, then renders the answer and its sources.

## Setup

```bash
cp .env.example .env      # then edit .env and set OPENAI_API_KEY
```

### Run everything with Docker

```bash
docker compose up --build
```

- Streamlit: http://localhost:8501
- Inngest dashboard: http://localhost:8288
- FastAPI: http://localhost:8000

### Run locally without Docker

You need four terminals, plus a local Qdrant:

```bash
docker run -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
uvicorn main:app --reload --port 8000
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest
streamlit run streamlit_app.py
```

## Configuration

All configuration is read from the environment (see `settings.py`). The values
that matter most:

| Variable                    | Default                 | Notes                                                   |
| --------------------------- | ----------------------- | ------------------------------------------------------- |
| `OPENAI_API_KEY`            | —                       | Required.                                               |
| `INNGEST_DEV`               | `true`                  | `false` switches to Inngest Cloud and requires keys.    |
| `INNGEST_EVENT_KEY`         | —                       | Required when `INNGEST_DEV=false`.                      |
| `INNGEST_SIGNING_KEY`       | —                       | Required when `INNGEST_DEV=false`.                      |
| `INNGEST_API_BASE_URL`      | `http://127.0.0.1:8288` | The Inngest REST API origin.                            |
| `QDRANT_URL`                | `http://localhost:6333` |                                                        |
| `QDRANT_COLLECTION`         | `docs`                  |                                                        |
| `QDRANT_DIM`                | `3072`                  | Must match the embedding model.                        |
| `UPLOADS_DIR`               | `uploads`               | Must be the **same path** for Streamlit and the worker. |

## Two things to know before deploying

### 1. `UPLOADS_DIR` must be a shared path

The `rag/ingest_pdf` event carries an absolute filesystem path, not file bytes.
The machine running the Inngest worker therefore has to see the same file at the
same path. In `docker-compose.yml` both `api` and `streamlit` mount the same
`uploads` volume at `/data/uploads` for this reason.

If you split these across separate hosts or platforms, this breaks. The fix is to
put uploads in object storage (S3, R2) and send a key instead of a path.

### 2. Re-ingesting the same filename is rate-limited

`RAG: Ingest PDF` carries `rate_limit(limit=1, period=4h, key=source_id)`, so
uploading a file with the same name twice within four hours will not re-ingest.
Delete the `rate_limit` block in `main.py` if you want repeated ingests.

## Inngest Cloud

Set `INNGEST_DEV=false` and provide `INNGEST_EVENT_KEY` plus
`INNGEST_SIGNING_KEY`. The Streamlit app hashes the signing key (sha256 of the
hex key, prefix stripped) to build the `Authorization: Bearer` header for REST
API calls, which is what lets it read run output.

Point the Inngest server at your deployed `api` service:

```bash
npx inngest-cli@latest serve -u https://your-api-host/api/inngest \
  --event-key "$INNGEST_EVENT_KEY" --signing-key "$INNGEST_SIGNING_KEY"
```

Put the Inngest dashboard behind auth or a VPN. It exposes your run history.

## Troubleshooting

- **"Could not reach the Inngest server"** — nothing is listening on
  `INNGEST_API_BASE_URL`. Confirm the Inngest container is up.
- **Timeout after 180s** — check the Inngest dashboard. Usually a run never
  started because of throttling or the 4-hour rate limit above.
- **401/403 from Inngest** — `INNGEST_SIGNING_KEY` is wrong or missing.
- **Empty answers with no sources** — the Qdrant collection is empty, or
  `QDRANT_DIM` does not match the embedding model (3072 for
  `text-embedding-3-large`).
- **Ingestion fails on a scanned PDF** — `PDFReader` does not OCR, so image-only
  pages yield no text.