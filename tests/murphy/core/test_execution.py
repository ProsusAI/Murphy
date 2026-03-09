"""Tests for execution helper functions (no browser/LLM calls)."""

from murphy.core.execution import (
	_extract_form_fills,
	_extract_urls_from_texts,
)

# ─── _extract_form_fills ─────────────────────────────────────────────────────


def test_extract_form_fills_empty():
	assert _extract_form_fills([]) == []


def test_extract_form_fills_no_input_actions():
	actions = [{'click': {'index': 1}}, {'navigate': {'url': 'https://example.com'}}]
	assert _extract_form_fills(actions) == []


def test_extract_form_fills_input_text():
	actions = [
		{
			'input_text': {'text': 'hello', 'index': 3},
			'interacted_element': {
				'ax_name': 'Email',
				'tag_name': 'input',
				'placeholder': 'Enter email',
				'attributes': {'name': 'email', 'aria-label': 'Email field', 'type': 'email'},
				'role': 'textbox',
			},
		}
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'hello'
	assert fills[0]['index'] == 3
	assert fills[0]['field_name'] == 'Email'
	assert fills[0]['tag'] == 'input'
	assert fills[0]['placeholder'] == 'Enter email'
	assert fills[0]['name_attr'] == 'email'
	assert fills[0]['aria_label'] == 'Email field'
	assert fills[0]['type_attr'] == 'email'
	assert fills[0]['role'] == 'textbox'


def test_extract_form_fills_input_key():
	"""The 'input' key is also recognized (not just 'input_text')."""
	actions = [{'input': {'text': 'world', 'index': 5}}]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'world'


def test_extract_form_fills_without_interacted_element():
	actions = [{'input_text': {'text': 'test', 'index': 1}}]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'test'
	assert 'field_name' not in fills[0]


def test_extract_form_fills_multiple():
	actions = [
		{'input_text': {'text': 'alice', 'index': 1}},
		{'click': {'index': 2}},
		{'input_text': {'text': 'password123', 'index': 3}},
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 2
	assert fills[0]['text'] == 'alice'
	assert fills[1]['text'] == 'password123'


def test_extract_form_fills_non_dict_val_ignored():
	"""Non-dict values for input_text are skipped."""
	actions = [{'input_text': 'not a dict'}]
	assert _extract_form_fills(actions) == []


def test_extract_form_fills_attributes_non_dict():
	"""If interacted_element.attributes is not a dict, don't crash."""
	actions = [
		{
			'input_text': {'text': 'x'},
			'interacted_element': {'ax_name': 'Field', 'tag_name': 'input', 'attributes': 'bad'},
		}
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['field_name'] == 'Field'


# ─── _extract_urls_from_texts ────────────────────────────────────────────────


def test_extract_urls_from_texts_empty():
	assert _extract_urls_from_texts([]) == []


def test_extract_urls_from_texts_no_urls():
	assert _extract_urls_from_texts(['no urls here', 'just plain text']) == []


def test_extract_urls_from_texts_single():
	result = _extract_urls_from_texts(['Error at https://example.com/page'])
	assert result == ['https://example.com/page']


def test_extract_urls_from_texts_multiple():
	result = _extract_urls_from_texts(
		[
			'Failed on https://a.com and http://b.com/path',
			'Also https://c.com',
		]
	)
	assert len(result) == 3


def test_extract_urls_from_texts_skips_none():
	result = _extract_urls_from_texts(['', 'https://ok.com'])
	assert result == ['https://ok.com']
