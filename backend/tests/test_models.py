import importlib
import pkgutil
import subprocess
import sys

from sqlalchemy import create_engine

import pumpkit
from pumpkit.db.base import Base

# Runs in a fresh interpreter so only the tables pumpkit.models registers are on Base.metadata.
_AUTOGENERATE = """
import sys
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import pumpkit.models  # noqa: F401
from pumpkit.db.base import Base

with create_engine(sys.argv[1]).connect() as connection:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    for diff in compare_metadata(context, Base.metadata):
        print(diff)
"""


def _import_every_pumpkit_module() -> None:
    for module in pkgutil.walk_packages(pumpkit.__path__, prefix="pumpkit."):
        if not module.name.endswith("__main__"):
            importlib.import_module(module.name)


def test_autogenerate_against_pumpkit_models_reports_no_changes(tmp_path):
    _import_every_pumpkit_module()
    url = f"sqlite:///{tmp_path / 'schema.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()

    result = subprocess.run(
        [sys.executable, "-c", _AUTOGENERATE, url], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
