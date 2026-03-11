from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.urls import api_router
import os

app = FastAPI(title="Scraper API")

# Ensure static directory exists
os.makedirs("static/screenshots", exist_ok=True)

# Mount static folder to serve screenshots
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include the main routing file from the app folder
app.include_router(api_router)

@app.get("/")
async def root():
    return {"message": "Welcome to Scraper API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
