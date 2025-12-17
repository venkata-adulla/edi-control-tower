# AI-Driven EDI Operations & Predictive Logistics Control Tower

We are building an enterprise PoC called **“AI-Driven EDI Operations & Predictive Logistics Control Tower”**.

## Tech stack

- **Streamlit frontend**
- **n8n backend** (webhook-based APIs)
- **AI for decision making** (LLM, ML)
- **No real external systems** (mock APIs via n8n)

## Key UI areas

1. **Chatbot** (Q&A over documents, shipments, SLAs)
2. **File upload** (automation trigger)
3. **KPI dashboard** (partner-based metrics)
4. **Incident drill-down**
5. **Role-based views** (Ops, Manager, Exec)

## Architecture note

All backend calls go through **n8n webhooks**.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Environment variables

- `EDI_ROLE`: `viewer` (default), `operator`, `admin`
- `N8N_BASE_URL`: defaults to `http://localhost:5678`
- `N8N_API_KEY`: optional, used for n8n REST API calls
- `N8N_INGEST_WEBHOOK_URL`: optional, enables forwarding uploads to an n8n webhook
- `N8N_CHAT_WEBHOOK_URL`: optional, enables chatbot answers via n8n
