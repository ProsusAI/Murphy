"""PCA scatter plot of persona clusters from personas.json.

Uses centroid scores jittered per cluster size — no re-running the pipeline needed.

Usage:
    python3 visualize_personas.py
    python3 visualize_personas.py --input output/personas.json --output output/pca_personas.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.decomposition import PCA


def load_data(path: Path) -> tuple[list[dict], list[str]]:
	data = json.loads(path.read_text())
	personas = data['result']['personas']
	dim_names = [d['name'] for d in data['schema']['dimensions']]
	return personas, dim_names


def build_point_cloud(
	personas: list[dict],
	seed: int = 42,
) -> tuple[np.ndarray, list[int], list[str]]:
	"""Jitter each centroid `size` times to approximate the original cluster distribution."""
	rng = np.random.default_rng(seed)
	points: list[np.ndarray] = []
	labels: list[int] = []
	names: list[str] = []

	for p in personas:
		centroid = np.array([s['score'] for s in p['centroid']], dtype=np.float64)
		n = p['size']
		noise = rng.normal(0, 0.35, (n, len(centroid)))
		pts = np.clip(centroid + noise, 1.0, 5.0)
		points.append(pts)
		labels.extend([p['persona_id']] * n)
		names.extend([p['name']] * n)

	return np.vstack(points), labels, names


def plot_pca(
	personas: list[dict],
	dim_names: list[str],
	output_path: Path,
) -> None:
	matrix, labels, _ = build_point_cloud(personas)

	pca = PCA(n_components=2, random_state=42)
	coords = pca.fit_transform(matrix)

	var1, var2 = pca.explained_variance_ratio_
	total_var = var1 + var2

	cmap = plt.colormaps['tab10']
	persona_map = {p['persona_id']: p for p in personas}
	unique_ids = sorted(persona_map)

	fig, ax = plt.subplots(figsize=(13, 9))

	for pid in unique_ids:
		p = persona_map[pid]
		mask = np.array([label == pid for label in labels])
		color = cmap(pid / max(len(unique_ids) - 1, 1))
		ax.scatter(
			coords[mask, 0],
			coords[mask, 1],
			color=color,
			alpha=0.45,
			s=22,
			label=f'{p["name"]} (n={p["size"]})',
		)
		# Mark centroid
		cx, cy = coords[mask, 0].mean(), coords[mask, 1].mean()
		ax.scatter(cx, cy, color=color, s=120, marker='*', edgecolors='black', linewidths=0.6, zorder=5)
		ax.annotate(
			p['name'].split()[0],
			(cx, cy),
			textcoords='offset points',
			xytext=(6, 4),
			fontsize=7.5,
			color=color,
			fontweight='bold',
		)

	ax.set_title(
		f'Persona clusters — PCA projection\n(jittered centroids · {total_var:.1%} variance explained · silhouette approx)',
		fontsize=12,
	)
	ax.set_xlabel(f'PC1 ({var1:.1%} variance)', fontsize=10)
	ax.set_ylabel(f'PC2 ({var2:.1%} variance)', fontsize=10)
	ax.legend(loc='lower right', fontsize=8, framealpha=0.8)
	ax.grid(True, linestyle='--', alpha=0.3)

	plt.tight_layout()
	output_path.parent.mkdir(parents=True, exist_ok=True)
	plt.savefig(output_path, dpi=150)
	print(f'Saved → {output_path}')


def main() -> None:
	parser = argparse.ArgumentParser(description='PCA scatter plot from personas.json')
	parser.add_argument('--input', type=Path, default=Path('output/personas.json'))
	parser.add_argument('--output', type=Path, default=Path('output/pca_personas.png'))
	args = parser.parse_args()

	personas, dim_names = load_data(args.input)
	print(f'Loaded {len(personas)} personas, {len(dim_names)} dimensions')
	plot_pca(personas, dim_names, args.output)


if __name__ == '__main__':
	main()
