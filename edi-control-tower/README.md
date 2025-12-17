# edi-control-tower

A minimal Streamlit-based EDI Control Tower scaffold with pages for KPIs, uploads, incidents, and a chatbot, plus optional integration points for n8n.

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
