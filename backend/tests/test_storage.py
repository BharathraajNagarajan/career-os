import io
import uuid
from pathlib import Path

import pytest

from app.artifacts.storage import FilesystemStorage, StorageKeyError, artifact_key, user_prefix


@pytest.fixture
def storage(tmp_path: Path) -> FilesystemStorage:
    return FilesystemStorage(tmp_path / "root")


def test_keys_are_generated_from_ids_only() -> None:
    user_id, artifact_id = uuid.uuid4(), uuid.uuid4()

    assert artifact_key(user_id, artifact_id) == f"users/{user_id}/artifacts/{artifact_id}"
    assert artifact_key(user_id, artifact_id).startswith(user_prefix(user_id))


def test_put_then_open_round_trips_bytes(storage: FilesystemStorage) -> None:
    storage.put("users/u1/artifacts/a1", io.BytesIO(b"hello"))

    with storage.open("users/u1/artifacts/a1") as handle:
        assert handle.read() == b"hello"


def test_put_never_overwrites_an_existing_key(storage: FilesystemStorage) -> None:
    storage.put("users/u1/artifacts/a1", io.BytesIO(b"first"))

    with pytest.raises(FileExistsError):
        storage.put("users/u1/artifacts/a1", io.BytesIO(b"second"))

    with storage.open("users/u1/artifacts/a1") as handle:
        assert handle.read() == b"first"


def test_put_leaves_no_temporary_files(storage: FilesystemStorage) -> None:
    storage.put("users/u1/artifacts/a1", io.BytesIO(b"data"))
    with pytest.raises(FileExistsError):
        storage.put("users/u1/artifacts/a1", io.BytesIO(b"data"))

    names = [path.name for path in (storage.root / "users/u1/artifacts").iterdir()]

    assert names == ["a1"]


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../outside",
        "users/../../outside",
        "users//double",
        "users/./dot",
        "users\\windows",
        "users/a\x00b",
    ],
)
def test_keys_that_escape_the_root_are_rejected(storage: FilesystemStorage, key: str) -> None:
    with pytest.raises(StorageKeyError):
        storage.put(key, io.BytesIO(b"x"))
    with pytest.raises(StorageKeyError):
        storage.open(key)
    with pytest.raises(StorageKeyError):
        storage.delete_prefix(key)


def test_a_symlink_pointing_outside_the_root_is_rejected(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"secret")
    storage.root.mkdir(parents=True)
    try:
        (storage.root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not permitted on this host")

    with pytest.raises(StorageKeyError):
        storage.open("link/secret")


def test_delete_prefix_removes_only_that_prefix(storage: FilesystemStorage) -> None:
    storage.put("users/u1/artifacts/a1", io.BytesIO(b"1"))
    storage.put("users/u1/artifacts/a2", io.BytesIO(b"2"))
    storage.put("users/u2/artifacts/b1", io.BytesIO(b"3"))

    storage.delete_prefix("users/u1/")

    assert not (storage.root / "users/u1").exists()
    with storage.open("users/u2/artifacts/b1") as handle:
        assert handle.read() == b"3"


def test_delete_prefix_is_idempotent_and_handles_single_keys(storage: FilesystemStorage) -> None:
    storage.put("users/u1/artifacts/a1", io.BytesIO(b"1"))

    storage.delete_prefix("users/u1/artifacts/a1")
    storage.delete_prefix("users/u1/artifacts/a1")
    storage.delete_prefix("users/never-existed/")

    with pytest.raises(FileNotFoundError):
        storage.open("users/u1/artifacts/a1")
