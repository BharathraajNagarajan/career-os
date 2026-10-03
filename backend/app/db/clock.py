from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def database_now(session: Session) -> datetime:
    return session.execute(select(func.now())).scalar_one()
