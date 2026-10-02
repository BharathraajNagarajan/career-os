from logging.config import fileConfig

from alembic import context

from app.config import MigrationSettings
from app.core.db import create_db_engine
from app.db.models import metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

engine = create_db_engine(MigrationSettings().migration_database_url)
try:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
