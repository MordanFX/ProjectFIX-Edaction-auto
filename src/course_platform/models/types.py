"""Helpers for portable SQL enum columns."""

from enum import Enum


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Persist string enum values rather than Python member names."""

    return [str(member.value) for member in enum_class]
