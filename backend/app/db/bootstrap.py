import sys

from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import text

from app.config import BootstrapSettings
from app.core.db import create_db_engine
from app.core.logging import configure_logging, get_logger

APP_ROLE = "career_os_app"
ROLE_ATTRIBUTES = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"

log = get_logger(__name__)


def bootstrap(owner_url: SecretStr, app_password: SecretStr) -> None:
    engine = create_db_engine(owner_url)
    try:
        with engine.begin() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": APP_ROLE}
            ).first()
            database: str = connection.execute(text("SELECT current_database()")).scalar_one()
            verb = "ALTER" if exists else "CREATE"
            statement = sql.SQL("{} ROLE {} WITH {} PASSWORD {}").format(
                sql.SQL(verb),
                sql.Identifier(APP_ROLE),
                sql.SQL(ROLE_ATTRIBUTES),
                sql.Literal(app_password.get_secret_value()),
            )
            grants = sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO {}; GRANT USAGE ON SCHEMA public TO {}"
            ).format(sql.Identifier(database), sql.Identifier(APP_ROLE), sql.Identifier(APP_ROLE))
            with connection.connection.driver_connection.cursor() as cursor:  # type: ignore[union-attr]
                cursor.execute(statement)
                cursor.execute(grants)
    finally:
        engine.dispose()


def main() -> int:
    settings = BootstrapSettings()
    configure_logging(settings)
    try:
        bootstrap(settings.migration_database_url, settings.app_db_password)
    except Exception as exc:
        log.error("db_bootstrap_failed", error_type=type(exc).__name__)
        return 1
    log.info("db_bootstrap_completed", outcome=APP_ROLE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
