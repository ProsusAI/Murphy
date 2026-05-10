"""Streamlit dashboard for visualizing persona discovery output.

Run:
    streamlit run murphy/personas/dashboard.py

Upload a ``personas.json`` file (produced by the persona discovery pipeline)
to explore the discovered personas, their trait-dimension scores, and the
session assignments.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
	page_title='Murphy Persona Dashboard',
	page_icon='🧭',
	layout='wide',
)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_json(raw: bytes | str) -> dict[str, Any]:
	if isinstance(raw, bytes):
		raw = raw.decode('utf-8')
	return json.loads(raw)


def _validate(data: dict[str, Any]) -> tuple[bool, str]:
	if not isinstance(data, dict):
		return False, 'Top-level JSON must be an object.'
	if 'schema' not in data or 'result' not in data:
		return False, "Missing required keys 'schema' and 'result'."
	if 'dimensions' not in data['schema']:
		return False, 'schema.dimensions is missing.'
	if 'personas' not in data['result']:
		return False, 'result.personas is missing.'
	return True, ''


def _centroid_to_dict(centroid: list[dict[str, Any]]) -> dict[str, float]:
	return {c['trait_name']: float(c['score']) for c in centroid}


def _personas_df(personas: list[dict[str, Any]]) -> pd.DataFrame:
	rows = []
	for p in personas:
		row = {
			'persona_id': p.get('persona_id'),
			'name': p.get('name', f'Persona {p.get("persona_id")}'),
			'description': p.get('description', ''),
			'size': p.get('size', 0),
			'test_orientation': p.get('test_orientation', ''),
			'distinguishing_traits': ', '.join(p.get('distinguishing_traits', []) or []),
		}
		row.update(_centroid_to_dict(p.get('centroid', [])))
		rows.append(row)
	return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

PERSONA_COLORS = px.colors.qualitative.Bold


def _color_for(idx: int) -> str:
	return PERSONA_COLORS[idx % len(PERSONA_COLORS)]


def render_overview(data: dict[str, Any]) -> None:
	result = data['result']
	personas = result.get('personas', [])
	assignments = result.get('assignments', []) or []
	dimensions = data['schema'].get('dimensions', [])

	c1, c2, c3, c4 = st.columns(4)
	c1.metric('Personas discovered', result.get('num_clusters', len(personas)))
	c2.metric('Trait dimensions', len(dimensions))
	c3.metric('Session assignments', len(assignments))
	sil = result.get('silhouette_score')
	c4.metric('Silhouette score', f'{sil:.3f}' if isinstance(sil, (int, float)) else '—')

	rationale = data['schema'].get('rationale')
	if rationale:
		st.caption(rationale)

	st.divider()

	left, right = st.columns([1, 1])

	with left:
		st.subheader('Persona size distribution')
		size_df = pd.DataFrame(
			[{'name': p.get('name', f'Persona {p["persona_id"]}'), 'size': p.get('size', 0)} for p in personas]
		).sort_values('size', ascending=False)
		fig = px.pie(size_df, names='name', values='size', hole=0.45, color_discrete_sequence=PERSONA_COLORS)
		fig.update_traces(textposition='inside', textinfo='percent+label')
		fig.update_layout(margin=dict(l=0, r=0, t=10, b=10), height=360)
		st.plotly_chart(fig, use_container_width=True)

	with right:
		st.subheader('Persona summary')
		st.dataframe(
			size_df.rename(columns={'name': 'Persona', 'size': 'Sessions'}),
			use_container_width=True,
			hide_index=True,
		)


def _radar_figure(personas: list[dict[str, Any]], dim_names: list[str]) -> go.Figure:
	fig = go.Figure()
	for i, p in enumerate(personas):
		cd = _centroid_to_dict(p.get('centroid', []))
		values = [cd.get(d, 0.0) for d in dim_names]
		values_closed = values + [values[0]]
		theta = dim_names + [dim_names[0]]
		fig.add_trace(
			go.Scatterpolar(
				r=values_closed,
				theta=theta,
				fill='toself',
				name=p.get('name', f'Persona {p["persona_id"]}'),
				line=dict(color=_color_for(i)),
				opacity=0.65,
			)
		)
	fig.update_layout(
		polar=dict(radialaxis=dict(visible=True, range=[1, 5])),
		showlegend=True,
		margin=dict(l=40, r=40, t=30, b=30),
		height=520,
	)
	return fig


def render_personas(data: dict[str, Any]) -> None:
	personas = data['result'].get('personas', [])
	dim_names = [d['name'] for d in data['schema']['dimensions']]

	if not personas:
		st.info('No personas found in this file.')
		return

	persona_labels = [f'{p.get("name", "Persona")} (id={p.get("persona_id")}, n={p.get("size", 0)})' for p in personas]
	choice = st.selectbox('Select a persona to inspect', persona_labels)
	selected_idx = persona_labels.index(choice)
	persona = personas[selected_idx]
	centroid = _centroid_to_dict(persona.get('centroid', []))

	header_left, header_right = st.columns([3, 1])
	with header_left:
		st.markdown(f'### {persona.get("name", "Persona")}')
		st.markdown(persona.get('description', ''))
	with header_right:
		st.metric('Sessions', persona.get('size', 0))
		if persona.get('test_orientation'):
			st.markdown(f'**Test orientation:** `{persona["test_orientation"]}`')

	if persona.get('distinguishing_traits'):
		st.markdown('**Distinguishing traits:**')
		cols = st.columns(len(persona['distinguishing_traits']) or 1)
		for i, t in enumerate(persona['distinguishing_traits']):
			cols[i].markdown(f'- {t}  \n  _score: {centroid.get(t, float("nan")):.2f}_')

	st.divider()

	left, right = st.columns([1, 1])

	with left:
		st.subheader('Trait scores (radar)')
		fig = _radar_figure([persona], dim_names)
		fig.update_traces(line_color=_color_for(selected_idx))
		st.plotly_chart(fig, use_container_width=True)

	with right:
		st.subheader('Trait scores (bar)')
		distinguishing = set(persona.get('distinguishing_traits', []) or [])
		bar_df = pd.DataFrame(
			[
				{
					'Dimension': d,
					'Score': centroid.get(d, 0.0),
					'Distinguishing': 'Distinguishing' if d in distinguishing else 'Other',
				}
				for d in dim_names
			]
		).sort_values('Score', ascending=True)
		fig = px.bar(
			bar_df,
			x='Score',
			y='Dimension',
			color='Distinguishing',
			color_discrete_map={'Distinguishing': _color_for(selected_idx), 'Other': '#b0b3bb'},
			orientation='h',
			range_x=[0, 5],
			text=bar_df['Score'].map(lambda v: f'{v:.2f}'),
		)
		fig.update_layout(
			height=520,
			margin=dict(l=10, r=10, t=10, b=10),
			yaxis_title='',
			legend_title_text='',
		)
		fig.update_traces(textposition='outside')
		st.plotly_chart(fig, use_container_width=True)

	with st.expander('Success criteria & execution hints'):
		if persona.get('success_criteria_guidance'):
			st.markdown('**Success criteria guidance**')
			st.write(persona['success_criteria_guidance'])
		hints = persona.get('execution_hints') or []
		if hints:
			st.markdown('**Execution hints**')
			for h in hints:
				st.markdown(f'- {h}')
		questions = persona.get('judge_questions') or []
		if questions:
			st.markdown('**Judge questions**')
			for q in questions:
				st.markdown(f'- {q}')


def render_comparison(data: dict[str, Any]) -> None:
	personas = data['result'].get('personas', [])
	dim_names = [d['name'] for d in data['schema']['dimensions']]

	if len(personas) < 1:
		st.info('No personas to compare.')
		return

	st.subheader('All personas — trait comparison (radar)')
	fig = _radar_figure(personas, dim_names)
	st.plotly_chart(fig, use_container_width=True)

	st.subheader('All personas — trait comparison (grouped bars)')
	rows = []
	for p in personas:
		cd = _centroid_to_dict(p.get('centroid', []))
		for d in dim_names:
			rows.append(
				{
					'Persona': p.get('name', f'Persona {p["persona_id"]}'),
					'Dimension': d,
					'Score': cd.get(d, 0.0),
				}
			)
	long_df = pd.DataFrame(rows)
	fig = px.bar(
		long_df,
		x='Dimension',
		y='Score',
		color='Persona',
		barmode='group',
		range_y=[0, 5],
		color_discrete_sequence=PERSONA_COLORS,
	)
	fig.update_layout(
		height=520,
		margin=dict(l=10, r=10, t=10, b=10),
		xaxis_tickangle=-30,
	)
	st.plotly_chart(fig, use_container_width=True)

	st.subheader('Centroid table')
	wide = long_df.pivot(index='Persona', columns='Dimension', values='Score').round(2)
	st.dataframe(wide, use_container_width=True)


def render_dimensions(data: dict[str, Any]) -> None:
	dims = data['schema'].get('dimensions', [])
	st.write(f'**{len(dims)} trait dimensions** — each persona is scored 1–5 on every dimension.')
	for d in dims:
		with st.expander(d['name']):
			if d.get('description'):
				st.markdown(f'**Description:** {d["description"]}')
			if d.get('why_chosen'):
				st.markdown(f'**Why chosen:** {d["why_chosen"]}')
			lc, hc = st.columns(2)
			with lc:
				st.markdown('**Low (1)**')
				st.write(d.get('low_description', ''))
			with hc:
				st.markdown('**High (5)**')
				st.write(d.get('high_description', ''))


def render_assignments(data: dict[str, Any]) -> None:
	assignments = data['result'].get('assignments') or []
	personas = data['result'].get('personas', [])

	if not assignments:
		st.info('No session assignments in this file.')
		return

	id_to_name = {p['persona_id']: p.get('name', f'Persona {p["persona_id"]}') for p in personas}
	df = pd.DataFrame(assignments)
	if 'persona_id' in df.columns:
		df['persona'] = df['persona_id'].map(id_to_name)

	c1, c2 = st.columns([1, 1])
	with c1:
		st.subheader('Sessions per persona')
		counts = df['persona'].value_counts().reset_index()
		counts.columns = ['Persona', 'Sessions']
		fig = px.bar(
			counts,
			x='Persona',
			y='Sessions',
			color='Persona',
			color_discrete_sequence=PERSONA_COLORS,
		)
		fig.update_layout(showlegend=False, height=360, margin=dict(l=10, r=10, t=10, b=10))
		st.plotly_chart(fig, use_container_width=True)

	with c2:
		st.subheader('Unique users per persona')
		if 'user_id' in df.columns:
			unique_users = df.groupby('persona')['user_id'].nunique().reset_index(name='Unique users')
			fig = px.bar(
				unique_users,
				x='persona',
				y='Unique users',
				color='persona',
				color_discrete_sequence=PERSONA_COLORS,
			)
			fig.update_layout(showlegend=False, height=360, margin=dict(l=10, r=10, t=10, b=10), xaxis_title='Persona')
			st.plotly_chart(fig, use_container_width=True)
		else:
			st.caption('No user_id field in assignments.')

	st.subheader('Assignment table')
	persona_filter = st.multiselect(
		'Filter by persona',
		options=sorted(df['persona'].dropna().unique().tolist()) if 'persona' in df.columns else [],
		default=[],
	)
	filtered = df if not persona_filter else df[df['persona'].isin(persona_filter)]
	st.dataframe(filtered, use_container_width=True, hide_index=True)
	st.download_button(
		'Download CSV',
		data=filtered.to_csv(index=False).encode('utf-8'),
		file_name='assignments.csv',
		mime='text/csv',
	)


# ---------------------------------------------------------------------------
# Sidebar / file selection
# ---------------------------------------------------------------------------


def _find_sample_files() -> list[Path]:
	root = Path(__file__).resolve().parents[2]
	output = root / 'murphy' / 'output'
	if not output.exists():
		return []
	return sorted(output.rglob('personas.json'))


def load_source() -> dict[str, Any] | None:
	st.sidebar.header('Data source')
	uploaded = st.sidebar.file_uploader(
		'Upload personas.json',
		type=['json'],
		accept_multiple_files=False,
	)

	sample_files = _find_sample_files()
	sample_choice = None
	if sample_files:
		options = ['— none —'] + [str(p.relative_to(Path(__file__).resolve().parents[2])) for p in sample_files]
		sample_choice = st.sidebar.selectbox('…or load a local sample', options, index=0)

	raw: bytes | str | None = None
	source_label = ''

	if uploaded is not None:
		raw = uploaded.read()
		source_label = uploaded.name
	elif sample_choice and sample_choice != '— none —':
		path = Path(__file__).resolve().parents[2] / sample_choice
		raw = path.read_bytes()
		source_label = sample_choice

	if raw is None:
		return None

	try:
		data = _load_json(raw)
	except json.JSONDecodeError as e:
		st.sidebar.error(f'Invalid JSON: {e}')
		return None

	ok, msg = _validate(data)
	if not ok:
		st.sidebar.error(f'Invalid persona output: {msg}')
		return None

	st.sidebar.success(f'Loaded: {source_label}')
	return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
	st.title('🧭 Murphy Persona Dashboard')
	st.caption('Explore personas discovered by the Murphy pipeline.')

	data = load_source()
	if data is None:
		st.info('Upload a `personas.json` file (or pick a sample) from the sidebar to begin.')
		with st.expander('Expected file structure'):
			st.code(
				'{\n'
				'  "schema": { "dimensions": [ {"name": ..., "description": ..., "low_description": ..., "high_description": ...} ] },\n'
				'  "result": {\n'
				'    "personas": [ {"persona_id": 0, "name": ..., "description": ..., "centroid": [{"trait_name": ..., "score": ...}], "distinguishing_traits": [...], "size": 63, ...} ],\n'
				'    "num_clusters": 2,\n'
				'    "silhouette_score": 0.46,\n'
				'    "assignments": [ {"session_id": ..., "user_id": ..., "persona_id": 0} ]\n'
				'  }\n'
				'}',
				language='json',
			)
		return

	overview_tab, personas_tab, compare_tab, dims_tab, assigns_tab = st.tabs(
		['Overview', 'Personas', 'Comparison', 'Dimensions', 'Assignments']
	)
	with overview_tab:
		render_overview(data)
	with personas_tab:
		render_personas(data)
	with compare_tab:
		render_comparison(data)
	with dims_tab:
		render_dimensions(data)
	with assigns_tab:
		render_assignments(data)

	with st.sidebar.expander('Raw JSON'):
		buf = io.StringIO()
		json.dump(data, buf, indent=2)
		st.download_button(
			'Download as-is',
			data=buf.getvalue(),
			file_name='personas.json',
			mime='application/json',
		)


if __name__ == '__main__':
	main()
