"""Interactive and non-interactive component selection."""

from __future__ import annotations

from src.extraction.models import ExtractedComponent


class SelectionError(ValueError):
    """Raised when the user supplies an invalid selection."""


def _parse_selection(selection: str, components: list[ExtractedComponent]) -> list[ExtractedComponent]:
    normalized = selection.strip().lower()
    if not normalized:
        raise SelectionError("Selection cannot be empty.")

    if normalized == "all":
        return list(components)

    available_indexes = {component.index: component for component in components}
    selected_indexes: list[int] = []
    for token in selection.replace(" ", "").split(","):
        if not token:
            continue
        if not token.isdigit():
            raise SelectionError(f"Invalid selection: '{token}' is not a component number.")
        index = int(token)
        if index not in available_indexes:
            raise SelectionError(
                f"Invalid selection: component {index} does not exist. "
                f"Available range: 1-{len(components)}."
            )
        if index not in selected_indexes:
            selected_indexes.append(index)

    if not selected_indexes:
        raise SelectionError("Selection cannot be empty.")

    return [available_indexes[index] for index in selected_indexes]


def select_components(
    components: list[ExtractedComponent],
    selection_arg: str | None = None,
) -> list[ExtractedComponent]:
    if not components:
        raise SelectionError("No components are available for selection.")

    if selection_arg is not None:
        return _parse_selection(selection_arg, components)

    while True:
        print('Select components to generate PDF.\nEnter numbers separated by comma, or type "all":')
        response = input("> ")
        try:
            return _parse_selection(response, components)
        except SelectionError as exc:
            print(f"Error: {exc}")
