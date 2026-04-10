"""conftest.py — pytest configuration for MedChronology tests."""
import os

# Set a dummy key so extractor imports without error during tests
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used-in-unit-tests")
