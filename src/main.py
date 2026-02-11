from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="API", version="0.1.0")


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
    return {"message": "Welcome to the API"}
