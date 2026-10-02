import io

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db


def test_sql_and_parameters_never_reach_logs(session: Session, log_stream: io.StringIO) -> None:
    user = make_user(session)
    make_event(session, user.id)
    session.execute(text("SELECT 1"))
    session.commit()

    output = log_stream.getvalue()
    assert "SELECT" not in output
    assert "INSERT" not in output
    assert user.primary_email not in output
