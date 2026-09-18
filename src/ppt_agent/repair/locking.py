"""Locking: element ids the repair layer must never touch."""

from __future__ import annotations

from typing import Any, Iterable

from .problem_detection import Problem


class LockSet:
    """Immutable set of locked element/page identifiers."""

    def __init__(self, ids: Iterable[str] = ()) -> None:
        self._ids = frozenset(str(item) for item in ids)

    def covers(self, problem: Problem) -> bool:
        """True when the problem's target intersects a locked id.

        A problem target like ``"3+5"`` (element pair) is covered when ANY of
        its parts is locked.
        """
        for part in problem.target_id.replace("+", " ").split():
            if part in self._ids:
                return True
        return False

    def __contains__(self, item: object) -> bool:
        return str(item) in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._ids))


def filter_locked(
    problems: list[Problem],
    locks: LockSet,
) -> tuple[list[Problem], list[dict[str, Any]]]:
    """Split problems into (actionable, locked-out). Never mutates input."""
    actionable: list[Problem] = []
    locked_out: list[dict[str, Any]] = []
    for problem in problems:
        if locks.covers(problem):
            locked_out.append({
                "signature": problem.signature,
                "code": problem.code,
                "reason": f"target {problem.target_id} is locked",
            })
        else:
            actionable.append(problem)
    return actionable, locked_out
