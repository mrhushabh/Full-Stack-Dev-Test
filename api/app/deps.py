"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.repository import Repository


def get_repo(session: Session = Depends(get_session)) -> Repository:
    """A repository bound to this request's database session."""
    return Repository(session)
