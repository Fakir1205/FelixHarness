"""scripts/ch12_test_smith.py - LangSmith config self-check.

Python does not read .env automatically, so load it explicitly before
printing the LANGSMITH_* variables visible to this process.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> None:
    """Print the LangSmith variables visible to this process."""
    print("TRACING:", os.environ.get("LANGSMITH_TRACING"))
    print("KEY:", os.environ.get("LANGSMITH_API_KEY", "")[:10])
    print("PROJECT:", os.environ.get("LANGSMITH_PROJECT"))


if __name__ == "__main__":
    main()
