from __future__ import annotations

import argparse
import csv
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

COLUMNS = [
	'uuid',
	'event',
	'distinct_id',
	'session_id',
	'timestamp',
	'properties',
	'elements_chain',
]


def _event(
	user_id: str,
	session_id: str,
	started_at: datetime,
	seconds: int,
	name: str,
	properties: dict[str, Any] | None = None,
	label: str = '',
) -> dict[str, str]:
	return {
		'uuid': uuid.uuid5(uuid.NAMESPACE_URL, f'{session_id}:{seconds}:{name}').hex,
		'event': name,
		'distinct_id': user_id,
		'session_id': session_id,
		'timestamp': (started_at + timedelta(seconds=seconds)).isoformat(),
		'properties': json.dumps(properties or {}, separators=(',', ':')),
		'elements_chain': f'button;text="{label}"' if label else '',
	}


def _pageview(
	user_id: str,
	session_id: str,
	started_at: datetime,
	seconds: int,
	path: str,
) -> dict[str, str]:
	return _event(
		user_id,
		session_id,
		started_at,
		seconds,
		'$pageview',
		{'$current_url': f'https://www.just-eat.co.uk{path}', '$pathname': path},
	)


def _quick_filter_session(index: int, started_at: datetime) -> list[dict[str, str]]:
	user_id = f'synthetic-user-qf-{index:02d}'
	session_id = f'synthetic-session-qf-{index:02d}'
	rows = [
		_pageview(user_id, session_id, started_at, 0, '/'),
		_event(user_id, session_id, started_at, 3, 'postcode_submitted', {'postcode_area': 'urban'}),
		_pageview(user_id, session_id, started_at, 5, '/area/ec1a-1bb'),
		_event(user_id, session_id, started_at, 7, '$autocapture', label='Filters'),
		_event(user_id, session_id, started_at, 9, 'dietary_filter_selected', {'filter_name': 'Vegan'}),
	]
	if index % 3 == 0:
		rows.extend(
			[
				_event(user_id, session_id, started_at, 11, '$rageclick', {'$rageclick_url': '/area/ec1a-1bb'}),
				_event(user_id, session_id, started_at, 14, 'search_results_loaded', {'result_count': 0}),
				_event(user_id, session_id, started_at, 18, 'session_abandoned', {'reason': 'no_immediate_results'}),
			]
		)
	else:
		rows.extend(
			[
				_event(user_id, session_id, started_at, 11, 'search_results_loaded', {'result_count': 18}),
				_event(user_id, session_id, started_at, 14, '$autocapture', label='Vegan burger'),
				_pageview(user_id, session_id, started_at, 16, '/menu/plant-kitchen'),
				_event(user_id, session_id, started_at, 20, 'item_added', {'dietary_tag': 'vegan', 'item_type': 'burger'}),
				_pageview(user_id, session_id, started_at, 22, '/checkout'),
			]
		)
	return rows


def _dietary_planner_session(index: int, started_at: datetime) -> list[dict[str, str]]:
	user_id = f'synthetic-user-dp-{index:02d}'
	session_id = f'synthetic-session-dp-{index:02d}'
	return [
		_pageview(user_id, session_id, started_at, 0, '/'),
		_event(user_id, session_id, started_at, 18, 'postcode_submitted', {'postcode_area': 'urban'}),
		_pageview(user_id, session_id, started_at, 23, '/area/ec1a-1bb'),
		_event(user_id, session_id, started_at, 42, 'dietary_filter_selected', {'filter_name': 'Vegan'}),
		_event(user_id, session_id, started_at, 65, 'restaurant_compared', {'comparison_count': 1}),
		_pageview(user_id, session_id, started_at, 86, '/menu/plant-kitchen'),
		_event(user_id, session_id, started_at, 110, 'allergen_information_opened', {'allergen': 'peanuts'}),
		_event(user_id, session_id, started_at, 145, 'menu_item_viewed', {'dietary_tag': 'vegan', 'item_type': 'pizza'}),
		_event(user_id, session_id, started_at, 181, 'restaurant_compared', {'comparison_count': 2}),
		_pageview(user_id, session_id, started_at, 210, '/menu/green-pizza'),
		_event(user_id, session_id, started_at, 242, 'allergen_information_opened', {'allergen': 'peanuts'}),
		_event(user_id, session_id, started_at, 275, 'item_added', {'dietary_tag': 'vegan', 'item_type': 'pizza'}),
		_pageview(user_id, session_id, started_at, 290, '/checkout'),
	]


def _low_supply_session(index: int, started_at: datetime) -> list[dict[str, str]]:
	user_id = f'synthetic-user-ls-{index:02d}'
	session_id = f'synthetic-session-ls-{index:02d}'
	rows = [
		_pageview(user_id, session_id, started_at, 0, '/'),
		_event(user_id, session_id, started_at, 14, 'postcode_submitted', {'postcode_area': 'remote'}),
		_pageview(user_id, session_id, started_at, 18, '/area/hs9-5xd'),
		_event(user_id, session_id, started_at, 22, 'search_results_loaded', {'result_count': 0}),
		_event(user_id, session_id, started_at, 35, '$autocapture', label='Change location'),
		_event(user_id, session_id, started_at, 48, 'postcode_submitted', {'postcode_area': 'remote_retry'}),
		_event(user_id, session_id, started_at, 54, 'search_results_loaded', {'result_count': 0}),
	]
	if index % 2 == 0:
		rows.extend(
			[
				_event(user_id, session_id, started_at, 70, '$rageclick', {'$rageclick_url': '/area/hs9-5xd'}),
				_event(user_id, session_id, started_at, 76, 'session_abandoned', {'reason': 'no_restaurants'}),
			]
		)
	else:
		rows.extend(
			[
				_event(user_id, session_id, started_at, 74, '$autocapture', label='Collection'),
				_event(user_id, session_id, started_at, 80, 'service_mode_changed', {'mode': 'collection'}),
				_event(user_id, session_id, started_at, 88, 'search_results_loaded', {'result_count': 0}),
				_event(user_id, session_id, started_at, 105, 'session_abandoned', {'reason': 'no_restaurants'}),
			]
		)
	return rows


def _repeat_buyer_session(index: int, started_at: datetime) -> list[dict[str, str]]:
	user_id = f'synthetic-user-rb-{index:02d}'
	session_id = f'synthetic-session-rb-{index:02d}'
	return [
		_pageview(user_id, session_id, started_at, 0, '/'),
		_event(user_id, session_id, started_at, 8, 'postcode_submitted', {'postcode_area': 'urban'}),
		_pageview(user_id, session_id, started_at, 12, '/area/ec1a-1bb'),
		_event(user_id, session_id, started_at, 20, '$autocapture', label='Order again'),
		_pageview(user_id, session_id, started_at, 24, '/menu/favourite-pizza'),
		_event(user_id, session_id, started_at, 33, 'item_added', {'item_type': 'pizza', 'source': 'order_again'}),
		_pageview(user_id, session_id, started_at, 38, '/checkout'),
		_event(user_id, session_id, started_at, 52, 'checkout_started', {'basket_items': 1}),
	]


def _confused_newcomer_session(index: int, started_at: datetime) -> list[dict[str, str]]:
	user_id = f'synthetic-user-cn-{index:02d}'
	session_id = f'synthetic-session-cn-{index:02d}'
	rows = [
		_pageview(user_id, session_id, started_at, 0, '/'),
		_event(user_id, session_id, started_at, 22, 'location_input_focused', {'visit_number': 1}),
		_event(user_id, session_id, started_at, 45, 'postcode_submitted', {'format': 'incomplete'}),
		_event(user_id, session_id, started_at, 48, 'validation_error_shown', {'error_type': 'invalid_postcode'}),
		_event(user_id, session_id, started_at, 72, 'postcode_submitted', {'format': 'with_extra_text'}),
		_event(user_id, session_id, started_at, 75, 'validation_error_shown', {'error_type': 'invalid_postcode'}),
		_event(user_id, session_id, started_at, 96, 'help_opened', {'topic': 'find_location'}),
		_event(user_id, session_id, started_at, 130, 'postcode_submitted', {'postcode_area': 'urban'}),
		_pageview(user_id, session_id, started_at, 138, '/area/ec1a-1bb'),
		_event(user_id, session_id, started_at, 170, 'category_opened', {'category': 'Groceries'}),
		_event(user_id, session_id, started_at, 196, 'back_navigation', {'reason': 'wrong_category'}),
		_event(user_id, session_id, started_at, 225, 'restaurant_opened', {'list_position': 1}),
		_pageview(user_id, session_id, started_at, 230, '/menu/example-restaurant'),
		_event(user_id, session_id, started_at, 268, 'item_information_opened', {'item_type': 'meal'}),
		_event(user_id, session_id, started_at, 310, 'add_attempted', {'required_options_missing': True}),
		_event(user_id, session_id, started_at, 313, 'validation_error_shown', {'error_type': 'required_option'}),
	]
	if index % 2 == 0:
		rows.extend(
			[
				_event(user_id, session_id, started_at, 350, 'help_opened', {'topic': 'required_options'}),
				_event(user_id, session_id, started_at, 390, 'item_added', {'item_type': 'meal'}),
				_pageview(user_id, session_id, started_at, 410, '/basket'),
			]
		)
	else:
		rows.append(_event(user_id, session_id, started_at, 345, 'session_abandoned', {'reason': 'confusing_flow'}))
	return rows


def generate(session_count_per_pattern: int) -> list[dict[str, str]]:
	start = datetime(2026, 8, 3, 17, 0, tzinfo=timezone.utc)
	builders = [
		_quick_filter_session,
		_dietary_planner_session,
		_low_supply_session,
		_repeat_buyer_session,
		_confused_newcomer_session,
	]
	rows: list[dict[str, str]] = []
	for pattern_index, builder in enumerate(builders):
		for index in range(1, session_count_per_pattern + 1):
			session_start = start + timedelta(days=index, hours=pattern_index * 2)
			rows.extend(builder(index, session_start))
	return sorted(rows, key=lambda row: (row['session_id'], row['timestamp']))


def main() -> None:
	parser = argparse.ArgumentParser(description='Generate synthetic PostHog events for the Murphy workshop.')
	parser.add_argument('--sessions-per-pattern', type=int, default=12)
	parser.add_argument('--output', type=Path, default=Path(__file__).with_name('synthetic_posthog_events.csv'))
	args = parser.parse_args()

	rows = generate(args.sessions_per_pattern)
	args.output.parent.mkdir(parents=True, exist_ok=True)
	with args.output.open('w', newline='') as output:
		writer = csv.DictWriter(output, fieldnames=COLUMNS)
		writer.writeheader()
		writer.writerows(rows)
	print(f'Wrote {len(rows)} events from {args.sessions_per_pattern * 5} sessions to {args.output}')


if __name__ == '__main__':
	main()
