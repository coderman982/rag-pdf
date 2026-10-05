"""Live end-to-end check of the event -> run -> poll path against the
docker compose stack (Inngest dev on :8288, api on :8000, qdrant on :6333)."""

import json

import httpx

import settings
import streamlit_app as s

print("api base :", settings.INNGEST_API_BASE_URL)
print("qdrant   :", settings.QDRANT_URL)
print("dev mode :", settings.INNGEST_DEV)
print()

# 1. Confirm Inngest knows about both functions.
try:
    r = httpx.get(f"{settings.INNGEST_API_BASE_URL}/v1/apps", timeout=15)
    print("apps endpoint:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        apps = data.get("data") or []
        for app in apps:
            print("  app:", app.get("name"), "-> functions:",
                  [f.get("name") for f in app.get("functions", [])])
except Exception as exc:
    print("apps endpoint failed:", exc)
print()

# 2. Send a real event and poll it through my own code path.
print("sending rag/query_pdf_ai ...")
event_id = s.send_event(
    "rag/query_pdf_ai", {"question": "What is this document about?", "top_k": 3}
)
print("event id:", event_id)
print()

# Show the raw run shape my polling code depends on.
resp = httpx.get(
    f"{settings.INNGEST_API_BASE_URL}/v1/events/{event_id}/runs",
    headers=s._auth_headers(),
    timeout=15,
)
print("raw runs status:", resp.status_code)
raw = resp.json()
print("raw runs body  :", json.dumps(raw)[:700])
print()

import time

deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    runs = s.fetch_runs(event_id)
    if runs:
        st = runs[0].get("status")
        key = st.lower() if isinstance(st, str) else st
        if key in s._STATUS_DONE:
            out = s._coerce_output(runs[0].get("output"))
            print("COMPLETED, parsed output:", json.dumps(out)[:500])
            break
        if key in s._STATUS_FAILED:
            print("run FAILED, status:", st)
            print("output:", json.dumps(runs[0].get("output"))[:600])
            break
        print("still running, status:", st)
    else:
        print("no run yet")
    time.sleep(2)
else:
    print("TIMED OUT")