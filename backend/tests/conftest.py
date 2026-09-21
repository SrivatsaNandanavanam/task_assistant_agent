import pytest

from app.db import session as db
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService


@pytest.fixture
def factory():
    return db.init_db("sqlite:///:memory:")


@pytest.fixture
def session(factory):
    s = factory()
    yield s
    s.close()


@pytest.fixture
def service(session):
    return TaskService(TaskRepository(session))
