# Imports every model so Base.metadata holds the whole schema for Alembic and the tests.
# A new models module must be added here, or tests/test_models.py fails.
import pumpkit.db.models  # noqa: F401
