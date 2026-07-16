"""Test setup: isolate the database to a temp file so tests never touch real data."""
import os
import tempfile

# Must be set before any app module imports the database engine.
_tmp = tempfile.NamedTemporaryFile(prefix="compliance-test-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

# Create tables now so endpoint tests that don't run the app's startup event still work.
from app.database import init_db  # noqa: E402

init_db()
