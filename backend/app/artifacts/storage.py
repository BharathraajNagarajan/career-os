import os
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

CHUNK_SIZE = 64 * 1024


class StorageKeyError(ValueError):
    pass


class StorageAdapter(Protocol):
    def put(self, key: str, source: BinaryIO) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete_prefix(self, prefix: str) -> None: ...


def user_prefix(user_id: uuid.UUID) -> str:
    return f"users/{user_id}/"


def artifact_key(user_id: uuid.UUID, artifact_id: uuid.UUID) -> str:
    return f"{user_prefix(user_id)}artifacts/{artifact_id}"


class FilesystemStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve(self, key: str) -> Path:
        trimmed = key.removesuffix("/")
        parts = trimmed.split("/")
        if (
            not trimmed
            or "\\" in trimmed
            or "\x00" in trimmed
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise StorageKeyError("invalid_storage_key")
        root = self.root.resolve()
        path = (root / trimmed).resolve()
        if root not in path.parents:
            raise StorageKeyError("invalid_storage_key")
        return path

    def put(self, key: str, source: BinaryIO) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                while chunk := source.read(CHUNK_SIZE):
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        return self._resolve(key).open("rb")

    def delete_prefix(self, prefix: str) -> None:
        path = self._resolve(prefix)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
