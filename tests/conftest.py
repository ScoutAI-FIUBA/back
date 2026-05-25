from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AUTH_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("AUTH_REFRESH_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_JWT_ISSUER", "scoutai")
os.environ.setdefault("AUTH_JWT_AUDIENCE", "scoutai-client")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5435/scoutai_dev")
