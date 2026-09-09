import pytest

from notebook_bot.models import User
from notebook_bot.storage import MemoryRepository


async def test_json_restart_and_rollback(tmp_path):
    path = tmp_path / "new" / "data.json"
    repo = MemoryRepository(path)
    async with repo.transaction() as tx:
        await tx.put(User(id="user", telegram_id=100, name="Анна"))
    with pytest.raises(RuntimeError):
        async with repo.transaction() as tx:
            await tx.put(User(id="bad", telegram_id=200, name="Bad"))
            raise RuntimeError("rollback")
    new = MemoryRepository(path)
    async with new.transaction() as tx:
        assert (await tx.get(User, "user")).name == "Анна"
        assert await tx.get(User, "bad") is None


async def test_failed_disk_write_does_not_commit(tmp_path, monkeypatch):
    repo = MemoryRepository(tmp_path / "data.json")

    def fail(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(repo, "_save", fail)
    with pytest.raises(OSError):
        async with repo.transaction() as tx:
            await tx.put(User(id="test", telegram_id=100, name="Test"))
    async with repo.transaction() as tx:
        assert await tx.get(User, "test") is None


def test_corrupt_json_not_overwritten(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(RuntimeError):
        MemoryRepository(path)
    assert path.read_text() == "broken"
