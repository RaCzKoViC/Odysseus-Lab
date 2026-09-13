import asyncio
from types import SimpleNamespace

from src.memory import MemoryManager
from src.memory_provider import NativeMemoryProvider
from src.memory_vector import MemoryVectorStore


def _seed(manager):
    entries = [
        manager.add_entry("global", owner="alice"),
        manager.add_entry("project a", owner="alice", project_id="project-a"),
        manager.add_entry("project b", owner="alice", project_id="project-b"),
        manager.add_entry("bob", owner="bob", project_id="project-a"),
    ]
    manager.save(entries)
    return entries


def test_memory_manager_project_visibility_modes(tmp_path):
    manager = MemoryManager(str(tmp_path))
    _seed(manager)

    assert [entry["text"] for entry in manager.load(
        owner="alice", project_id="project-a", mode="project_only"
    )] == ["project a"]
    assert [entry["text"] for entry in manager.load(
        owner="alice", project_id="project-a", mode="project_plus_global"
    )] == ["global", "project a"]
    assert [entry["text"] for entry in manager.load(
        owner="alice", project_id="project-a", mode="inherit"
    )] == ["global", "project a", "project b"]


def test_memory_vector_add_stores_owner_and_project_metadata():
    added = []

    class Collection:
        def get(self, ids):
            return {"ids": []}

        def add(self, **kwargs):
            added.append(kwargs)

    lane = SimpleNamespace(
        name="fastembed",
        collection=Collection(),
        encode=lambda texts: [[0.1, 0.2] for _ in texts],
    )
    store = MemoryVectorStore.__new__(MemoryVectorStore)
    store._healthy = True
    store._lanes = [lane]

    store.add("memory-id", "text", owner="alice", project_id="project-a")

    assert added[0]["metadatas"] == [
        {"source": "memory", "owner": "alice", "project_id": "project-a"}
    ]


def test_native_provider_round_trips_project_scope(tmp_path):
    manager = MemoryManager(str(tmp_path))
    provider = NativeMemoryProvider(manager)

    record = asyncio.run(
        provider.remember(
            "project fact",
            owner="alice",
            project_id="project-a",
        )
    )
    other = manager.add_entry("other", owner="alice", project_id="project-b")
    entries = manager.load_all_for_update()
    entries.append(other)
    manager.save(entries)

    listed = asyncio.run(
        provider.list_memories(
            owner="alice",
            project_id="project-a",
            memory_mode="project_only",
        )
    )
    assert record.project_id == "project-a"
    assert [item.text for item in listed] == ["project fact"]
