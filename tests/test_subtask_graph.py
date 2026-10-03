import pytest

from codemill.models import SubTask
from codemill.subtask_graph import order_subtasks


def test_orders_subtasks_by_dependencies_stably():
    subtasks = (
        SubTask("ST-002", "integrate", depends_on=("ST-001",)),
        SubTask("ST-003", "independent"),
        SubTask("ST-001", "build primitive"),
    )

    ordered = order_subtasks(subtasks)

    assert [subtask.id for subtask in ordered] == ["ST-003", "ST-001", "ST-002"]


def test_rejects_unknown_dependencies():
    subtasks = (SubTask("ST-001", "integrate", depends_on=("ST-999",)),)

    with pytest.raises(ValueError, match="unmet dependencies: ST-999"):
        order_subtasks(subtasks)


def test_rejects_duplicate_subtask_ids():
    subtasks = (SubTask("ST-001", "first"), SubTask("ST-001", "second"))

    with pytest.raises(ValueError, match="duplicate sub-task IDs: ST-001"):
        order_subtasks(subtasks)


def test_rejects_duplicate_dependencies():
    subtasks = (
        SubTask("ST-001", "first"),
        SubTask("ST-002", "second", depends_on=("ST-001", "ST-001")),
    )

    with pytest.raises(ValueError, match="duplicate dependencies for ST-002: ST-001"):
        order_subtasks(subtasks)


def test_rejects_dependency_cycles():
    subtasks = (
        SubTask("ST-001", "first", depends_on=("ST-002",)),
        SubTask("ST-002", "second", depends_on=("ST-001",)),
    )

    with pytest.raises(ValueError, match="dependency cycle detected"):
        order_subtasks(subtasks)
