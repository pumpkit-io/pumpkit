import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("missing", ["X_CLIENT_ID", "X_CLIENT_SECRET", "TRIAL_IDENTITY_KEYS"])
def test_an_instance_refuses_missing_x_only_settings(missing):
    env = dict(os.environ)
    env.update(
        X_CLIENT_ID="local-client",
        X_CLIENT_SECRET="local-secret",
        TRIAL_IDENTITY_KEYS='{"active":"test","keys":{"test":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}}',
    )
    env[missing] = ""
    result = subprocess.run(
        [sys.executable, "-c", "from pumpkit.core.config import settings"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert missing in result.stderr


def test_an_instance_refuses_invalid_credential_encryption():
    env = dict(os.environ, FERNET_ENCRYPTION_KEY="invalid")
    result = subprocess.run(
        [sys.executable, "-c", "from pumpkit.core.config import settings"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "FERNET_ENCRYPTION_KEY" in result.stderr


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.org/callback",
        "https://example.org?code=private",
        "https://user:private@example.org",
    ],
)
def test_callback_origin_configuration_is_validated_without_logging_its_values(origin):
    result = subprocess.run(
        [sys.executable, "-c", "from pumpkit.core.config import settings"],
        env=dict(os.environ, PUBLIC_URL=origin),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "PUBLIC_URL" in result.stderr
    assert "private" not in result.stderr
