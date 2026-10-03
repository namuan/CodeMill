import heapq

from .models import SubTask


def order_subtasks(subtasks: tuple[SubTask, ...]) -> tuple[SubTask, ...]:
    positions: dict[str, int] = {}
    for index, subtask in enumerate(subtasks):
        if subtask.id in positions:
            raise ValueError(f"duplicate sub-task IDs: {subtask.id}")
        positions[subtask.id] = index

    known_ids = set(positions)
    for subtask in subtasks:
        dependencies = set(subtask.depends_on)
        if len(dependencies) != len(subtask.depends_on):
            duplicates = sorted(
                dependency
                for dependency in dependencies
                if subtask.depends_on.count(dependency) > 1
            )
            raise ValueError(
                f"duplicate dependencies for {subtask.id}: {', '.join(duplicates)}"
            )
        missing = dependencies - known_ids
        if missing:
            raise ValueError(
                f"{subtask.id} has unmet dependencies: {', '.join(sorted(missing))}"
            )

    dependents = {subtask.id: [] for subtask in subtasks}
    remaining_dependencies = {subtask.id: set(subtask.depends_on) for subtask in subtasks}
    ready = [
        (positions[subtask.id], subtask.id)
        for subtask in subtasks
        if not subtask.depends_on
    ]
    heapq.heapify(ready)
    ordered_ids: list[str] = []

    for subtask in subtasks:
        for dependency in subtask.depends_on:
            dependents[dependency].append(subtask.id)

    while ready:
        _, subtask_id = heapq.heappop(ready)
        ordered_ids.append(subtask_id)
        for dependent in dependents[subtask_id]:
            remaining_dependencies[dependent].remove(subtask_id)
            if not remaining_dependencies[dependent]:
                heapq.heappush(ready, (positions[dependent], dependent))

    if len(ordered_ids) != len(subtasks):
        cyclic_ids = sorted(known_ids - set(ordered_ids))
        raise ValueError(f"dependency cycle detected: {', '.join(cyclic_ids)}")

    subtasks_by_id = {subtask.id: subtask for subtask in subtasks}
    return tuple(subtasks_by_id[subtask_id] for subtask_id in ordered_ids)
