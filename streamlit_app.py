import hashlib
import json
import re
import time
from pathlib import Path

import httpx
import inngest
import streamlit as st

import settings

st.set_page_config(page_title="RAG Ingest PDF", page_icon="📄", layout="centered")


def get_inngest_client() -> inngest.Inngest:
    """Build an Inngest client in the mode the current environment dictates.

    A fresh client per call is intentional. Streamlit re-runs this script on
    every interaction, and the SDK's HTTP client binds to the event loop it was
    first used on. Caching it across re-runs risks "Event loop is closed"
    errors. We only ever use the synchronous send path, so no loop is needed.
    """
    return inngest.Inngest(
        app_id=settings.INNGEST_APP_ID,
        is_production=not settings.INNGEST_DEV,
        event_key=settings.INNGEST_EVENT_KEY,
        signing_key=settings.INNGEST_SIGNING_KEY,
        env=settings.INNGEST_ENV,
        api_base_url=settings.INNGEST_API_BASE_URL,
        event_api_base_url=settings.INNGEST_EVENT_API_BASE_URL,
    )


def _auth_headers() -> dict[str, str]:
    """Authorization header for the Inngest REST API.

    In dev mode no auth is required. Against Inngest Cloud the signing key must
    be hashed (sha256 of the hex key, prefix stripped) and sent as a bearer
    token. This mirrors net.fetch_with_auth_fallback in the SDK.
    """
    headers = {"Content-Type": "application/json"}
    key = settings.INNGEST_SIGNING_KEY
    if key and not settings.INNGEST_DEV:
        prefix = re.match(r"^signkey-[\w]+-", key)
        raw = key[prefix.end() :] if prefix else key
        token = hashlib.sha256(bytearray.fromhex(raw)).hexdigest()
        headers["Authorization"] = f"Bearer {token}"
    return headers


def save_uploaded_pdf(file) -> Path:
    settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", file.name)
    file_path = settings.UPLOADS_DIR / safe_name
    file_path.write_bytes(file.getbuffer())
    return file_path


def send_event(name: str, data: dict) -> str:
    """Send an event and return its ID."""
    client = get_inngest_client()
    ids = client.send_sync(inngest.Event(name=name, data=data))
    if not ids:
        raise RuntimeError(f"Inngest accepted '{name}' but returned no event ID")
    return ids[0]


# Run statuses, per the Inngest API. Cloud returns ints, the dev server
# returns strings, so both are normalised here.
_STATUS_DONE = {2, "2", "completed", "succeeded", "success", "finished", "done"}
_STATUS_FAILED = {0, "0", 1, "1", "failed", "cancelled", "canceled"}
_STATUS_RUNNING = {3, "3", "running", "queued", "in_progress"}


def _coerce_output(raw) -> dict:
    """The dev server returns output as an object; the cloud API may return
    a JSON-encoded string. Handle both."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def fetch_runs(event_id: str) -> list[dict]:
    url = f"{settings.INNGEST_API_BASE_URL}/v1/events/{event_id}/runs"
    try:
        resp = httpx.get(url, headers=_auth_headers(), timeout=15)
    except httpx.HTTPError as err:
        raise RuntimeError(
            f"Could not reach the Inngest server at {settings.INNGEST_API_BASE_URL}. "
            f"Is it running? ({err})"
        ) from err

    if resp.status_code == 401 or resp.status_code == 403:
        raise RuntimeError(
            "Inngest rejected the request (401/403). Check INNGEST_SIGNING_KEY."
        )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()

    data = resp.json()
    runs = data.get("data", []) if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def wait_for_run_output(
    event_id: str,
    timeout_s: float = 180.0,
    poll_interval_s: float = 1.0,
) -> dict:
    """Block until the triggered function finishes, then return its output."""
    deadline = time.monotonic() + timeout_s
    last_status = None

    while True:
        runs = fetch_runs(event_id)
        if runs:
            run = runs[0]
            status = run.get("status")
            status_key = status.lower() if isinstance(status, str) else status
            last_status = status if last_status is None else last_status

            if status_key in _STATUS_DONE:
                return _coerce_output(run.get("output"))

            if status_key in _STATUS_FAILED:
                raise RuntimeError(f"Ingestion failed (run status: {status})")

        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Timed out after {timeout_s:.0f}s waiting for the run "
                f"(last status: {last_status or 'no run created yet'}). "
                "Check the Inngest dashboard for throttling or rate limits."
            )

        time.sleep(poll_interval_s)


def show_config_problems() -> bool:
    problems = settings.missing_config()
    if not problems:
        return True
    st.error("Configuration is incomplete - the app cannot work yet:")
    for problem in problems:
        st.markdown(f"- {problem}")
    st.caption("Copy .env.example to .env and fill in the missing values.")
    return False


st.title("RAG PDF")

ready = show_config_problems()

if ready:
    mode = "dev server" if settings.INNGEST_DEV else "Inngest Cloud"
    st.caption(f"Qdrant: {settings.QDRANT_URL} - Inngest: {mode}")

    st.subheader("Ingest a PDF")
    uploaded = st.file_uploader("Choose a PDF", type=["pdf"])

    if uploaded is not None:
        path = save_uploaded_pdf(uploaded)
        try:
            with st.spinner(f"Ingesting {path.name}..."):
                event_id = send_event(
                    "rag/ingest_pdf",
                    {
                        "pdf_path": str(path),
                        "source_id": path.name,
                    },
                )
                output = wait_for_run_output(event_id)
            st.success(
                f"Ingested {output.get('ingested', 0)} chunks from {path.name}"
            )
            st.caption(f"Event ID: {event_id}")
        except (RuntimeError, TimeoutError, httpx.HTTPError) as err:
            st.error(f"Ingestion failed: {err}")

    st.divider()
    st.subheader("Ask a question")

    with st.form("rag_query_form"):
        question = st.text_input("Your question")
        top_k = st.number_input(
            "How many chunks to retrieve", min_value=1, max_value=20, value=5, step=1
        )
        submitted = st.form_submit_button("Ask")

    if submitted and question.strip():
        try:
            with st.spinner("Searching and generating an answer..."):
                event_id = send_event(
                    "rag/query_pdf_ai",
                    {"question": question.strip(), "top_k": int(top_k)},
                )
                output = wait_for_run_output(event_id)
        except (RuntimeError, TimeoutError, httpx.HTTPError) as err:
            st.error(f"Query failed: {err}")
        else:
            answer = output.get("answer") or "(No answer)"
            sources = output.get("sources") or []

            st.markdown("**Answer**")
            st.write(answer)

            if sources:
                st.markdown("**Sources**")
                for src in sources:
                    st.markdown(f"- {src}")
            else:
                st.info(
                    "No sources retrieved. If you just uploaded a PDF, it may "
                    "still be indexing, or the embed dimension in Qdrant "
                    "may not match the embedding model."
                )
else:
    st.stop()