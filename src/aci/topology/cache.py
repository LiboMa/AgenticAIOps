"""In-Memory Graph Cache — singleton with periodic refresh and alarm injection.

Holds the current ``InfraGraph`` snapshot in memory, refreshes on a
configurable interval, records topology deltas between refreshes, and
supports live node-status updates from CloudWatch alarms.

Graceful degradation: ``get_current()`` returns ``None`` when the graph
hasn't been built yet — callers (RCA pipeline) skip the topology section.

Ref: docs/designs/GRAPH_FAULT_PROPAGATION_DESIGN.md §4-5
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Callable, Coroutine

from .delta import capture_delta, get_delta_store
from .engine import InfraGraph
from .types import NodeStatus

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL = int(os.environ.get("GRAPH_CACHE_REFRESH_S", "60"))


class GraphCache:
    """In-memory graph cache with periodic background refresh.

    Usage::

        from src.aci.topology.cache import graph_cache

        graph = graph_cache.get_current()      # O(1)
        if graph is None:
            # graceful degrade — skip topology section
            ...

    The background refresh task must be started explicitly via
    :meth:`start_refresh_loop` (called from ``api_server`` lifespan).
    """

    def __init__(self, refresh_interval_s: int | None = None) -> None:
        self._graph: InfraGraph | None = None
        self._previous: InfraGraph | None = None
        self._last_refresh: datetime | None = None
        self._stale: bool = False
        self._lock = asyncio.Lock()
        self._refresh_interval = refresh_interval_s or _REFRESH_INTERVAL
        self._refresh_task: asyncio.Task[None] | None = None
        self._builder: Callable[[], Coroutine[Any, Any, InfraGraph]] | None = None

    # ── Configuration ────────────────────────────────────────────────

    def set_builder(
        self,
        builder: Callable[[], Coroutine[Any, Any, InfraGraph]],
    ) -> None:
        """Register the async function that builds a fresh :class:`InfraGraph`.

        The builder is called on every refresh cycle.  Typically wraps
        ``collector.py`` + ``engine.py`` calls::

            async def _build() -> InfraGraph:
                topo = await collect_vpc_topology(...)
                g = InfraGraph()
                g.build_from_vpc_topology(topo)
                return g

            graph_cache.set_builder(_build)
        """
        self._builder = builder

    # ── Read ─────────────────────────────────────────────────────────

    def get_current(self) -> InfraGraph | None:
        """Return the cached graph (O(1)).  ``None`` if not yet built."""
        return self._graph

    def get_previous(self) -> InfraGraph | None:
        """Return the previous snapshot (before the last refresh)."""
        return self._previous

    def is_available(self) -> bool:
        """``True`` when a graph has been built at least once."""
        return self._graph is not None

    @property
    def is_stale(self) -> bool:
        return self._stale

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    # ── Refresh ──────────────────────────────────────────────────────

    async def refresh(self) -> None:
        """Build a new graph, diff against the previous, and store deltas."""
        if self._builder is None:
            logger.warning("GraphCache.refresh() called without a builder — skipping")
            return

        async with self._lock:
            try:
                new_graph = await self._builder()
            except Exception:
                logger.exception("Graph builder failed; keeping previous graph")
                return

            # Capture deltas
            if self._graph is not None:
                try:
                    deltas = capture_delta(self._graph, new_graph, source="discovery")
                    if deltas:
                        store = get_delta_store()
                        store.store(deltas)
                        logger.info("Captured %d topology deltas", len(deltas))
                except Exception:
                    logger.exception("Delta capture/store failed (non-fatal)")

            self._previous = self._graph
            self._graph = new_graph
            self._last_refresh = datetime.utcnow()
            self._stale = False
            logger.debug(
                "Graph refreshed: %d nodes, %d edges",
                new_graph.node_count,
                new_graph.edge_count,
            )

    # ── Alarm injection (between refreshes) ──────────────────────────

    async def inject_alarm(
        self,
        resource_id: str,
        alarm_state: str,
    ) -> bool:
        """Update a node's status from an incoming alarm.

        Maps CloudWatch alarm states to :class:`NodeStatus`:
          - ``ALARM``            → ``error``
          - ``INSUFFICIENT_DATA``→ ``warning``
          - ``OK``               → ``healthy``

        Also marks the cache as **stale** so the next refresh cycle runs
        a full rebuild (dual-effect: status update + invalidation).

        Returns ``True`` if the node was found and updated.
        """
        if self._graph is None:
            return False

        state_map = {
            "ALARM": NodeStatus.ERROR,
            "INSUFFICIENT_DATA": NodeStatus.WARNING,
            "OK": NodeStatus.HEALTHY,
        }
        status = state_map.get(alarm_state.upper(), NodeStatus.WARNING)

        g = self._graph.graph
        if resource_id not in g:
            logger.debug("inject_alarm: node %s not in graph", resource_id)
            return False

        g.nodes[resource_id]["status"] = status
        self._stale = True  # triggers rebuild on next refresh cycle
        logger.info(
            "Alarm injected: %s → %s (cache marked stale)", resource_id, status,
        )
        return True

    # ── Invalidation ─────────────────────────────────────────────────

    def invalidate(self) -> None:
        """Mark the cache as stale.  The next refresh will rebuild."""
        self._stale = True

    # ── Background refresh loop ──────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodic refresh task (runs forever until cancelled)."""
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in graph refresh loop")

            interval = self._refresh_interval
            if self._stale:
                # Stale cache → refresh sooner (min 5s debounce)
                interval = max(5, interval // 4)

            await asyncio.sleep(interval)

    def start_refresh_loop(self) -> None:
        """Start the background refresh task.

        Safe to call multiple times — duplicate calls are no-ops.
        """
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="graph-cache-refresh",
        )
        logger.info(
            "Graph cache refresh loop started (interval=%ds)", self._refresh_interval,
        )

    def stop_refresh_loop(self) -> None:
        """Cancel the background refresh task."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            self._refresh_task = None
            logger.info("Graph cache refresh loop stopped")

    # ── Stats (for /api/topology/status) ─────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return cache status for health / debug endpoints."""
        return {
            "available": self.is_available(),
            "stale": self._stale,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "refresh_interval_s": self._refresh_interval,
            "node_count": self._graph.node_count if self._graph else 0,
            "edge_count": self._graph.edge_count if self._graph else 0,
        }


# ── Module-level singleton ───────────────────────────────────────────

graph_cache = GraphCache()
