from collections.abc import Generator

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.db import SessionLocal

app = FastAPI(title="InvoiceScope API")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health_check(_: Session = Depends(get_db)) -> dict[str, str]:
    return {"status": "ok"}
