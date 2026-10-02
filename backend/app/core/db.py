from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker


def database_url(raw: SecretStr) -> URL:
    return make_url(raw.get_secret_value()).set(drivername="postgresql+psycopg")


def create_db_engine(raw: SecretStr) -> Engine:
    return create_engine(database_url(raw), pool_pre_ping=True, hide_parameters=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
