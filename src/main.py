from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.models import CombatRequest, NegotiateRequest
from src.strategy import decide_combat, decide_negotiation

app = FastAPI(title="Kingdom Wars Bot", version="0.1.0")


@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return JSONResponse(
        status_code=200,
        content={
            "status": "OK",
        }
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to Kingdom Wars Bot"}


@app.post("/negotiate")
async def negotiate(req: NegotiateRequest):
    """Negotiation phase — propose alliances and coordinate attacks."""
    proposals = decide_negotiation(req)
    return JSONResponse(content=proposals)


@app.post("/combat")
async def combat(req: CombatRequest):
    """Combat phase — decide armor, attacks, and upgrades."""
    actions = decide_combat(req)
    return JSONResponse(content=actions)
