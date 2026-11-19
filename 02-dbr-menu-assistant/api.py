"""Small HTTP API around the menu assistant, for n8n (and later WhatsApp) to call.

    uvicorn api:app --port 8000

POST /chat  {"message": "...", "channel": "whatsapp", "sender": "..."}  ->  {"reply": "...", ...}
GET  /health

The API keeps no chat history and stores nothing about the sender. "sender" is accepted so a
WhatsApp integration can pass it through, but it is never logged or sent to the model.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from assistant import MAX_MESSAGE_CHARS, Assistant, AssistantError

app = FastAPI(title="Dum Biryani Rasoi menu assistant", version="1.0")
# Optional shared secret, so only your n8n can call the API once it is reachable from outside.
API_TOKEN = os.getenv("ASSISTANT_API_TOKEN", "")
_bot: Assistant | None = None


def bot() -> Assistant:
    global _bot
    if _bot is None:
        _bot = Assistant()  # loads the embedding model once, on the first request
    return _bot


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    channel: str = "webhook"
    sender: str | None = None


class ChatOut(BaseModel):
    reply: str
    cited_items: list[str]
    order_summary: str
    whatsapp_link: str
    fallback: bool
    cost_usd: float


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, x_api_token: str | None = Header(default=None)) -> ChatOut:
    if API_TOKEN and x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="missing or wrong X-API-Token header")
    try:
        answer = bot().ask(body.message[:MAX_MESSAGE_CHARS])
    except AssistantError as e:
        raise HTTPException(status_code=503, detail=str(e))
    d = answer.to_dict()
    return ChatOut(reply=d["reply"], cited_items=d["cited_items"], order_summary=d["order_summary"],
                   whatsapp_link=d["whatsapp_link"], fallback=d["fallback"], cost_usd=d["cost_usd"])
