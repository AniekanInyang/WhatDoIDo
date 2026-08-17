from fastapi import FastAPI


app = FastAPI(
    title="WhatDoIDo API",
    description="Backend API for the WhatDoIDo personal decision engine.",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
