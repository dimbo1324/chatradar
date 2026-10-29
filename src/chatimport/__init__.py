"""ChatImport: local, reactive export of chosen Telegram groups and channels to JSONL."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chatimport")
except PackageNotFoundError:  # pragma: no cover — running from sources without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
