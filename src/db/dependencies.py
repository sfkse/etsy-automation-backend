from collections.abc import Generator

from sqlalchemy.orm import Session

from src.db.session import SessionLocal


def get_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
