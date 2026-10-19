"""ЧатРадар: сбор, очистка и поиск полезной информации в чатах мессенджеров."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chatradar")
except PackageNotFoundError:  # pragma: no cover — запуск из исходников без установки
    __version__ = "0.0.0"

__all__ = ["__version__"]
