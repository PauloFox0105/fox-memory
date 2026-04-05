"""Minimal tests for FoxMemory — no DB required."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

# Prevent real DB connection during import
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("FOXMEMORY_API_KEY", "test-key")


def test_validate_memory_valid():
    """Test that validate_memory accepts valid input."""
    from api_v3 import validate_memory
    # Should not raise
    validate_memory("session-1", "test context", {"key": "value"})


def test_validate_memory_empty_session():
    """Test that validate_memory rejects empty session_id."""
    from api_v3 import validate_memory
    with pytest.raises(ValueError):
        validate_memory("", "test context", {"key": "value"})


def test_validate_memory_empty_contexto():
    """Test that validate_memory rejects empty contexto."""
    from api_v3 import validate_memory
    with pytest.raises(ValueError):
        validate_memory("session-1", "", {"key": "value"})


def test_memory_text():
    """Test _memory_text builds a proper string."""
    from api_v3 import _memory_text
    result = _memory_text("test context", {"tool": "pytest"}, "testing")
    assert "test context" in result
    assert "pytest" in result


def test_app_exists():
    """Test FastAPI app can be imported."""
    from api_v3 import app
    assert app is not None
    assert app.title or True  # FastAPI app exists


def test_health_endpoint_exists():
    """Test that /health route is registered."""
    from api_v3 import app
    routes = [r.path for r in app.routes]
    assert "/health" in routes
