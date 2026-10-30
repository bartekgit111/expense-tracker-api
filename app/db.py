import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Where is the database? Read it from an environment variable,
# or use a local SQLite file if none is set.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./expenses.db")


class Base(DeclarativeBase):
    """The parent of all our tables. SQLAlchemy uses it to know which tables exist."""


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Give each request its own conversation with the database, and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()