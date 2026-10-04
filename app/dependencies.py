from pathlib import Path
from app.models.db import setup_database
from app.config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "app.db"
SessionLocal = setup_database(DB_PATH)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
