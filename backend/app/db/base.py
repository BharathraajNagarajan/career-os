import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class TextEnum[E: StrEnum](TypeDecorator[E]):
    impl = Text
    cache_ok = True

    def __init__(self, enum_class: type[E]) -> None:
        super().__init__()
        self.enum_class = enum_class

    def process_bind_param(self, value: E | str | None, dialect: Dialect) -> str | None:
        return None if value is None else self.enum_class(value).value

    def process_result_value(self, value: Any, dialect: Dialect) -> E | None:
        return None if value is None else self.enum_class(value)


def enum_check(column: str, enum_class: type[StrEnum]) -> CheckConstraint:
    allowed = ", ".join(f"'{member.value}'" for member in enum_class)
    return CheckConstraint(f"{column} IN ({allowed})", name=column)


class HasId:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class HasCreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserOwned(HasId):
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


def owned_table_args(*args: Any) -> tuple[Any, ...]:
    return (UniqueConstraint("user_id", "id"), *args)


def owned_fk(column: str, target_table: str, **kwargs: Any) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["user_id", column], [f"{target_table}.user_id", f"{target_table}.id"], **kwargs
    )


class StateVersioned:
    state_version: Mapped[int] = mapped_column(server_default="1")
