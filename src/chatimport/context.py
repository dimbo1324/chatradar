"""What the service needs to start: the loaded configuration, the folders and the gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chatimport.config import Config, load_config
from chatimport.paths import AppPaths, app_paths, library_path, resolve_root
from chatimport.ports import ChatImportError
from chatimport.telegram.client import TelethonGateway

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import Clock


@dataclass(frozen=True, slots=True)
class ServiceContext:
    config: Config
    paths: AppPaths
    root: Path
    library_file: Path


def load_context(root_override: str | None = None, base: Path | None = None) -> ServiceContext:
    paths = app_paths(base)
    config = load_config(paths.config_file)
    root = resolve_root(root_override, config.output.root_dir)
    library_file = library_path(config.library.file, paths)
    paths.ensure()
    return ServiceContext(config=config, paths=paths, root=root, library_file=library_file)


def build_gateway(ctx: ServiceContext, clock: Clock) -> TelethonGateway:
    if not ctx.config.telegram.is_configured:
        raise ChatImportError("telegram api_id and api_hash are not set in config.toml")
    return TelethonGateway(
        ctx.config.telegram,
        ctx.paths.session_file,
        include_sender_names=ctx.config.output.include_sender_names,
        include_raw=ctx.config.output.include_raw,
        clock=clock,
    )
