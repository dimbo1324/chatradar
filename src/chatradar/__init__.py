"""ChatRadar: collect, clean and search useful information in messenger chats."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chatradar")
except PackageNotFoundError:  # pragma: no cover — running from sources without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
