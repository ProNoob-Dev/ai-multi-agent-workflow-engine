"""Shared fixtures: every test gets a fresh JSON store (temp file) and a
fresh in-memory vector store, seeded with the policy documents."""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app import store as store_mod
from app import vectorstore as vs_mod
from app.seed import seed_all
from app.store import JsonStore
from app.vectorstore import InMemoryVectorStore


@pytest.fixture()
def tmp_store(tmp_path):
    s = JsonStore(str(tmp_path / "store.json"))
    store_mod.set_store(s)
    yield s
    store_mod.set_store(None)


@pytest.fixture()
def tmp_vector_store():
    vs = InMemoryVectorStore()
    vs_mod.set_vector_store(vs)
    yield vs
    vs_mod.set_vector_store(None)


@pytest.fixture()
def seeded(tmp_store, tmp_vector_store):
    seed_all()
    return tmp_store


@pytest.fixture()
def checkpointer():
    return MemorySaver()
