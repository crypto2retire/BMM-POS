import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from app.routers import auth, vendors, items, sales, pos, assistant

app = FastAPI(title="BMM-POS", description="Bowenstreet Market POS System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(items.router, prefix="/api/v1")
app.include_router(sales.router, prefix="/api/v1")
app.include_router(pos.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
