from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from app.services.job_manager import job_manager
from app.routes import locations, jobs, progress

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    job_manager.init_app()
    yield
    # Shutdown
    job_manager.shutdown()

app = FastAPI(
    title="MAHA Bhulekh 7/12 Bulk Downloader",
    description="Automated bulk downloader for Maharashtra Bhulekh 7/12 extracts",
    version="0.1.0",
    lifespan=lifespan
)

# Avoid wildcard CORS for same-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include Routers
app.include_router(locations.router)
app.include_router(jobs.router)
app.include_router(progress.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
