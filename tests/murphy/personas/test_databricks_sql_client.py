"""Tests for Databricks SQL client auth selection."""

from unittest.mock import MagicMock, patch

import pytest

from murphy.personas.databricks_sql_client import DatabricksSqlClient


@pytest.fixture
def mock_dbsql():
	with patch('murphy.personas.databricks_sql_client.DatabricksSqlClient._connect') as connect:
		yield connect


def test_token_auth_used_when_token_set():
	client = DatabricksSqlClient(
		host='dbc.example.com',
		token='pat-token',
		warehouse_id='wh-1',
	)
	with patch('databricks.sql.connect') as connect:
		connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
		connect.return_value.__exit__ = MagicMock(return_value=False)
		with patch.object(client, '_connect', wraps=client._connect):
			with patch('databricks.sql') as dbsql_module:
				dbsql_module.connect = connect
				client._query_sync('SELECT 1', {})
	connect.assert_called_once()
	assert connect.call_args.kwargs['access_token'] == 'pat-token'
	assert connect.call_args.kwargs['server_hostname'] == 'dbc.example.com'


def test_cli_profile_auth_when_no_token():
	mock_cfg = MagicMock()
	mock_cfg.host = 'https://dbc.example.com'
	mock_cfg.authenticate = MagicMock()

	with (
		patch('murphy.personas.databricks_sql_client.DATABRICKS_HOST', ''),
		patch('murphy.personas.databricks_sql_client.DATABRICKS_TOKEN', ''),
		patch('databricks.sdk.core.Config', return_value=mock_cfg) as config_cls,
		patch('databricks.sql.connect') as connect,
	):
		client = DatabricksSqlClient(profile='my-profile', warehouse_id='wh-1')
		connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
		connect.return_value.__exit__ = MagicMock(return_value=False)
		from databricks import sql as dbsql

		client._connect(dbsql)

	assert config_cls.call_args.kwargs['profile'] == 'my-profile'
	connect.assert_called_once()
	provider = connect.call_args.kwargs['credentials_provider']
	assert provider() is mock_cfg.authenticate
	assert connect.call_args.kwargs['server_hostname'] == 'dbc.example.com'


def test_warehouse_id_required():
	with patch('murphy.personas.databricks_sql_client.DATABRICKS_WAREHOUSE_ID', ''):
		with pytest.raises(ValueError, match='warehouse ID'):
			DatabricksSqlClient(token='x', host='h')


def test_parse_cell_converts_nested_rows():
	from databricks.sql.types import Row

	from murphy.personas.databricks_sql_client import _parse_cell

	parsed = _parse_cell([Row(event_name='$pageview', pathname='/home')])
	assert parsed == [{'event_name': '$pageview', 'pathname': '/home'}]
