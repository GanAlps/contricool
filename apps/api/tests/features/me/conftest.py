"""Re-use the transactions-feature fixture wiring + add me_repo."""
from collections.abc import Iterator

import pytest

from app.features.me import repository as me_repo
from tests.features.transactions.conftest import (  # noqa: F401
    txn_client,
    txn_env,
)


@pytest.fixture(autouse=True)
def _wire_me_repo(txn_env: dict[str, object]) -> Iterator[None]:  # noqa: F811 — re-export of the conftest fixture by the same name is intentional
    """Point the me-feature's table cache at the same moto Users table
    that ``txn_env`` set up for friends + auth + transactions."""
    me_repo._set_table_for_tests(txn_env["users_table"])  # type: ignore[arg-type]
    try:
        yield
    finally:
        me_repo._set_table_for_tests(None)
