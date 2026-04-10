"""conftest.py — pytest configuration for MedChronology tests."""
import os
import sys

# Add root folder to path so tests can import extractor.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a dummy key so extractor imports without error during tests
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used-in-unit-tests")
