from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.account import router as account_router
from app.api.decisions import router as decisions_router
from app.core.config import get_settings


app = FastAPI(
    title="WhatDoIDo API",
    description="Backend API for the WhatDoIDo personal decision engine.",
    version="0.1.0",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(decisions_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
