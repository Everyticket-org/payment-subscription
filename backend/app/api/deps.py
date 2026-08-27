"""Shared FastAPI dependencies."""
from typing import Generator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.database import get_db

__all__ = ["get_db", "get_application"]


def get_application(application_code: str = "EVERYTICKET", db: Session = Depends(get_db)) -> Application:
    """
    Resolve the Application row for the current request. V1 only ever has
    one application (EVERYTICKET, spec section 2), but every lookup goes
    through this dependency so a second application can be added later
    (e.g. from a subdomain or header) without touching call sites.
    """
    application = db.query(Application).filter(Application.code == application_code).first()
    if application is None:
        raise HTTPException(status_code=404, detail=f"Unknown application '{application_code}'")
    return application
