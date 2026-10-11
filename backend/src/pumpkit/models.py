# Imports every model so Base.metadata holds the whole schema for Alembic and the tests.
# A new models module must be added here, or tests/test_models.py fails.
import pumpkit.auth.models  # noqa: F401
import pumpkit.authors.models  # noqa: F401
import pumpkit.billing.models  # noqa: F401
import pumpkit.core.db.models  # noqa: F401
import pumpkit.x_connection.models  # noqa: F401
