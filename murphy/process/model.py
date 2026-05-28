from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


class NavigationModel:
	"""Builds and persists a goal-keyed URL transition graph from Murphy run history.

	Stored as: { base_url: { goal_key: { from_url: { to_url: count } } } }

	On each run, the visited URL sequence is added to the graph under the run's goal.
	Before each run, the most-travelled pages for that goal are returned as navigation hints.
	"""

	def __init__(self, path: Path) -> None:
		self.path = path
		self._data: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
		if path.exists():
			self._load()

	def update(self, base_url: str, pages_visited: list[str], goal: str | None = None) -> None:
		"""Add a URL sequence from a completed test run to the graph."""
		base = self._base(base_url)
		gkey = self._goal_key(goal)
		if base not in self._data:
			self._data[base] = {}
		if gkey not in self._data[base]:
			self._data[base][gkey] = {}
		graph = self._data[base][gkey]
		relevant = [p for p in pages_visited if self._base(p) == base]
		for i in range(len(relevant) - 1):
			from_url = self._normalise(relevant[i])
			to_url = self._normalise(relevant[i + 1])
			if from_url not in graph:
				graph[from_url] = {}
			graph[from_url][to_url] = graph[from_url].get(to_url, 0) + 1

	def get_hints(self, base_url: str, goal: str | None = None) -> list[str] | None:
		"""Return an ordered list of the most-visited pages for this base URL and goal.

		Returns None if there is not enough data yet (fewer than 3 transitions).
		Falls back to goal_key='default' if no goal-specific data exists.
		"""
		base = self._base(base_url)
		base_data = self._data.get(base)
		if not base_data:
			return None

		gkey = self._goal_key(goal)
		graph = base_data.get(gkey)
		if not graph:
			# Fuzzy fallback: find a stored key that contains or is contained by the query
			for stored_key, stored_graph in base_data.items():
				if stored_key != 'default' and (gkey in stored_key or stored_key in gkey):
					graph = stored_graph
					break
		if not graph:
			graph = base_data.get('default')
		if not graph:
			return None

		visit_counts: dict[str, int] = {}
		for destinations in graph.values():
			for url, count in destinations.items():
				visit_counts[url] = visit_counts.get(url, 0) + count
		if sum(visit_counts.values()) < 3:
			return None
		sorted_pages = sorted(visit_counts, key=lambda u: visit_counts[u], reverse=True)
		return sorted_pages[:10]

	def save(self) -> None:
		"""Persist the graph to disk."""
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps(self._data, indent=2))

	def _load(self) -> None:
		try:
			self._data = json.loads(self.path.read_text())
		except Exception:
			self._data = {}

	@staticmethod
	def _base(url: str) -> str:
		parsed = urlparse(url)
		return f'{parsed.scheme}://{parsed.netloc}'

	@staticmethod
	def _normalise(url: str) -> str:
		parsed = urlparse(url)
		return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')

	@staticmethod
	def _goal_key(goal: str | None) -> str:
		if not goal:
			return 'default'
		return goal.strip().lower()
