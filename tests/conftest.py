import os

# Set a dummy DATABASE_URL before any db imports so create_async_engine doesn't fail at import time.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://fm:changeme@localhost/fuelmonitor"
)

import pytest  # noqa: E402, F401
