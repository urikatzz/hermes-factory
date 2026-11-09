"""Snapshot contracts shared by collection and aggregation."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourcePaths:
    board_db: Path
    board_id: str
    hermes_home: Path
    published_state: Path | None
    evidence_root: Path | None


@dataclass(frozen=True)
class Snapshot:
    board_id: str
    generated_at: str
    sources: tuple[dict, ...]
    tasks: tuple[dict, ...]
    runs: tuple[dict, ...]
    events: tuple[dict, ...]
    sessions: tuple[dict, ...]
    published: dict
    evidence: tuple[dict, ...]
    warnings: tuple[dict, ...]
