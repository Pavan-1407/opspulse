import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="opspulse-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp / 'test.db'}")
os.environ.setdefault("MODEL_DIR", str(_tmp / "models"))
os.environ.setdefault("STATIC_DIR", str(_tmp / "static"))
os.environ.setdefault("HISTORY_DAYS", "150")
os.environ.setdefault("SEED_ON_STARTUP", "true")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
