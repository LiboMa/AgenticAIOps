"""Topology Delta Storage — capture, store, and query graph changes over time.

Compares two ``InfraGraph`` snapshots and records structural deltas
(node/edge additions, removals, attribute changes) in SQLite.

Supports time-travel rebuild and recent-change summaries for RCA enrichment.

Ref: docs/designs/GRAPH_FAULT_PROPAGATION_DESIGN.md §3
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

from .engine import InfraGraph

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

_DEFAULT_DB_DIR = os.environ.get("AIOPS_DATA_DIR", "data")
_RETENTION_DAYS = int(os.environ.get("TOPO_DELTA_RETENTION_DAYS", "7"))


# ── Data model ───────────────────────────────────────────────────────


@dataclass
class TopologyChange:
    """A single topology delta record."""

    change_type: str           # node_added | node_removed | node_updated | edge_added | edge_removed
    entity_id: str             # Node ID or "src->dst" for edges
    entity_type: str = ""      # NodeType enum value
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    source: str = "discovery"  # discovery | cloudtrail | manual
    source_detail: str = ""
    region: str = ""
    account_id: str = ""
    timestamp: str = ""        # ISO 8601 — filled on persist

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── SQLite store ─────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS topology_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    change_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL,
    entity_type   TEXT,
    old_value     TEXT,
    new_value     TEXT,
    source        TEXT    NOT NULL DEFAULT 'discovery',
    source_detail TEXT,
    region        TEXT,
    account_id    TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_topo_changes_time   ON topology_changes(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_topo_changes_entity ON topology_changes(entity_id);",
    "CREATE INDEX IF NOT EXISTS idx_topo_changes_source ON topology_changes(source);",
]


class DeltaStore:
    """SQLite-backed topology delta storage.

    Thread-safe — each call opens its own connection or uses a passed one.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            Path(_DEFAULT_DB_DIR).mkdir(parents=True, exist_ok=True)
            db_path = os.path.join(_DEFAULT_DB_DIR, "topology_deltas.db")
        self._db_path = db_path
        self._ensure_schema()

    # ── Internal helpers ─────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                conn.execute(idx_sql)

    # ── Write ────────────────────────────────────────────────────────

    def store(self, changes: list[TopologyChange]) -> int:
        """Persist a batch of topology changes.  Returns count stored."""
        if not changes:
            return 0
        now = datetime.now(tz=timezone.utc).isoformat()
        rows = []
        for c in changes:
            rows.append((
                c.timestamp or now,
                c.change_type,
                c.entity_id,
                c.entity_type,
                json.dumps(c.old_value) if c.old_value is not None else None,
                json.dumps(c.new_value) if c.new_value is not None else None,
                c.source,
                c.source_detail,
                c.region,
                c.account_id,
            ))
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO topology_changes
                   (timestamp, change_type, entity_id, entity_type,
                    old_value, new_value, source, source_detail, region, account_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        logger.info("Stored %d topology deltas", len(rows))
        return len(rows)

    # ── Read / query ─────────────────────────────────────────────────

    def get_recent(
        self,
        window: timedelta | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[TopologyChange]:
        """Query recent topology changes.

        Args:
            window: Time window (default 1 hour).
            entity_id: Filter to a specific node/edge.
            limit: Max rows returned.
        """
        if window is None:
            window = timedelta(hours=1)
        since = (datetime.now(tz=timezone.utc) - window).isoformat()

        sql = "SELECT * FROM topology_changes WHERE timestamp >= ?"
        params: list[Any] = [since]

        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_change(r) for r in rows]

    def get_between(
        self,
        start: datetime,
        end: datetime,
    ) -> list[TopologyChange]:
        """Get deltas between two timestamps (for time-travel rebuild)."""
        sql = """SELECT * FROM topology_changes
                 WHERE timestamp >= ? AND timestamp <= ?
                 ORDER BY timestamp DESC"""
        with self._connect() as conn:
            rows = conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall()
        return [self._row_to_change(r) for r in rows]

    # ── Retention / cleanup ──────────────────────────────────────────

    def purge_old(self, retention_days: int | None = None) -> int:
        """Delete deltas older than retention period.  Returns count deleted."""
        days = retention_days or _RETENTION_DAYS
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM topology_changes WHERE timestamp < ?", (cutoff,),
            )
            deleted = cursor.rowcount
        if deleted:
            logger.info("Purged %d topology deltas older than %d days", deleted, days)
        return deleted

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_change(row: sqlite3.Row) -> TopologyChange:
        return TopologyChange(
            change_type=row["change_type"],
            entity_id=row["entity_id"],
            entity_type=row["entity_type"] or "",
            old_value=json.loads(row["old_value"]) if row["old_value"] else None,
            new_value=json.loads(row["new_value"]) if row["new_value"] else None,
            source=row["source"],
            source_detail=row["source_detail"] or "",
            region=row["region"] or "",
            account_id=row["account_id"] or "",
            timestamp=row["timestamp"],
        )


# ── Singleton (module-level) ─────────────────────────────────────────

_delta_store: DeltaStore | None = None


def get_delta_store(db_path: str | None = None) -> DeltaStore:
    """Get or create the module-level DeltaStore singleton."""
    global _delta_store
    if _delta_store is None:
        _delta_store = DeltaStore(db_path=db_path)
    return _delta_store


# ── Delta capture ────────────────────────────────────────────────────


def capture_delta(
    old_graph: InfraGraph | None,
    new_graph: InfraGraph,
    source: str = "discovery",
    source_detail: str = "",
) -> list[TopologyChange]:
    """Compare two graph snapshots and produce a list of deltas.

    Called after each graph rebuild (60s poll cycle) to record what changed.
    If *old_graph* is ``None`` (first build), all nodes/edges are ``added``.
    """
    changes: list[TopologyChange] = []
    now = datetime.now(tz=timezone.utc).isoformat()

    old_g = old_graph.graph if old_graph else None
    new_g = new_graph.graph

    old_nodes = set(old_g.nodes) if old_g else set()
    new_nodes = set(new_g.nodes)

    # ── Node additions ───────────────────────────────────────────────
    for node_id in new_nodes - old_nodes:
        attrs = dict(new_g.nodes[node_id])
        changes.append(TopologyChange(
            change_type="node_added",
            entity_id=node_id,
            entity_type=attrs.get("node_type", ""),
            new_value=_sanitize_attrs(attrs),
            source=source,
            source_detail=source_detail,
            timestamp=now,
        ))

    # ── Node removals ────────────────────────────────────────────────
    for node_id in old_nodes - new_nodes:
        attrs = dict(old_g.nodes[node_id])  # type: ignore[union-attr]
        changes.append(TopologyChange(
            change_type="node_removed",
            entity_id=node_id,
            entity_type=attrs.get("node_type", ""),
            old_value=_sanitize_attrs(attrs),
            source=source,
            source_detail=source_detail,
            timestamp=now,
        ))

    # ── Node updates (status / attribute changes) ────────────────────
    for node_id in old_nodes & new_nodes:
        old_attrs = dict(old_g.nodes[node_id])  # type: ignore[union-attr]
        new_attrs = dict(new_g.nodes[node_id])
        if old_attrs != new_attrs:
            changes.append(TopologyChange(
                change_type="node_updated",
                entity_id=node_id,
                entity_type=new_attrs.get("node_type", ""),
                old_value=_sanitize_attrs(old_attrs),
                new_value=_sanitize_attrs(new_attrs),
                source=source,
                source_detail=source_detail,
                timestamp=now,
            ))

    # ── Edge diffs ───────────────────────────────────────────────────
    old_edges = set(old_g.edges) if old_g else set()
    new_edges = set(new_g.edges)

    for src, dst in new_edges - old_edges:
        edge_data = dict(new_g.edges[src, dst])
        changes.append(TopologyChange(
            change_type="edge_added",
            entity_id=f"{src}->{dst}",
            entity_type=edge_data.get("edge_type", ""),
            new_value=_sanitize_attrs(edge_data),
            source=source,
            source_detail=source_detail,
            timestamp=now,
        ))

    for src, dst in old_edges - new_edges:
        edge_data = dict(old_g.edges[src, dst])  # type: ignore[union-attr]
        changes.append(TopologyChange(
            change_type="edge_removed",
            entity_id=f"{src}->{dst}",
            entity_type=edge_data.get("edge_type", ""),
            old_value=_sanitize_attrs(edge_data),
            source=source,
            source_detail=source_detail,
            timestamp=now,
        ))

    return changes


def _sanitize_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Make graph attributes JSON-serialisable (drop non-primitive values)."""
    clean: dict[str, Any] = {}
    for k, v in attrs.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            clean[k] = v
        elif isinstance(v, dict):
            clean[k] = _sanitize_attrs(v)
        elif isinstance(v, (list, tuple)):
            clean[k] = list(v)
        else:
            clean[k] = str(v)
    return clean


# ── Summary formatter (for RCA prompt injection) ─────────────────────


def format_recent_changes(
    changes: list[TopologyChange],
    max_items: int = 15,
) -> str:
    """Format recent topology changes as a human-readable string for RCA."""
    if not changes:
        return "No topology changes in the time window."

    lines: list[str] = []
    for c in changes[:max_items]:
        ts = c.timestamp[:19] if c.timestamp else "?"
        if c.change_type == "node_added":
            lines.append(f"  [{ts}] + Node {c.entity_id} ({c.entity_type}) added")
        elif c.change_type == "node_removed":
            lines.append(f"  [{ts}] - Node {c.entity_id} ({c.entity_type}) removed")
        elif c.change_type == "node_updated":
            old_status = (c.old_value or {}).get("status", "?")
            new_status = (c.new_value or {}).get("status", "?")
            lines.append(f"  [{ts}] ~ Node {c.entity_id}: {old_status} → {new_status}")
        elif c.change_type == "edge_added":
            lines.append(f"  [{ts}] + Edge {c.entity_id} ({c.entity_type})")
        elif c.change_type == "edge_removed":
            lines.append(f"  [{ts}] - Edge {c.entity_id} ({c.entity_type})")

    if len(changes) > max_items:
        lines.append(f"  ... and {len(changes) - max_items} more changes")

    return "\n".join(lines)
