from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .deps import get_db

app = FastAPI(title="CareCircle API", version="0.1.0")


@app.get("/health")
def health():
    """Is the API process up?"""
    return {"status": "ok"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    """Can the API reach PostgreSQL?"""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unreachable")
    return {"status": "ok", "database": "connected"}