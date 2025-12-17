# AI-Driven EDI Operations & Predictive Logistics Control Tower

We are building an enterprise PoC called **“AI-Driven EDI Operations & Predictive Logistics Control Tower”**.

Project scaffold lives in `edi-control-tower/`.

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
