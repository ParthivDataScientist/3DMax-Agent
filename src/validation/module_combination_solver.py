"""Module-combination solver for Luminy frame widths."""

from __future__ import annotations

from collections import Counter


def _rank_key(solution: dict) -> tuple[object, ...]:
    return (
        int(solution.get("module_count", 999)),
        float(solution.get("waste_mm", 999999.0)),
        float(solution.get("combined_width_mm", 999999.0)),
    )


def _build_solution(target_width_mm: float, combination: list[float]) -> dict:
    counts = Counter(int(round(value)) for value in combination)
    combined_width = sum(combination)
    modules = [
        {
            "name": f"Luminy Frame W{width_mm}",
            "quantity": quantity,
        }
        for width_mm, quantity in sorted(counts.items())
    ]
    return {
        "type": "modular_combination",
        "modules": modules,
        "combined_width_mm": round(float(combined_width), 3),
        "difference_mm": round(abs(float(combined_width) - float(target_width_mm)), 3),
        "waste_mm": round(max(float(combined_width) - float(target_width_mm), 0.0), 3),
        "module_count": int(sum(counts.values())),
    }


def find_modular_solutions(
    target_width_mm: float,
    available_module_widths_mm: list[float],
    *,
    tolerance_mm: float = 5.0,
    max_solutions: int = 5,
    max_modules: int = 6,
) -> list[dict]:
    widths = sorted({int(round(value)) for value in available_module_widths_mm if value > 0})
    if not widths:
        return []

    target = int(round(float(target_width_mm)))
    max_width = max(widths)
    max_total = target + max(max_width, int(round(tolerance_mm))) + (max_width * max_modules)

    dp: dict[int, list[int]] = {0: []}
    for total in range(max_total + 1):
        if total not in dp:
            continue
        current_combo = dp[total]
        if len(current_combo) >= max_modules:
            continue
        for width in widths:
            new_total = total + width
            if new_total > max_total:
                continue
            new_combo = current_combo + [width]
            existing = dp.get(new_total)
            if existing is None or len(new_combo) < len(existing):
                dp[new_total] = new_combo

    candidate_totals = [
        total
        for total in dp
        if total != 0 and abs(total - target) <= max_width
    ]
    solutions = [_build_solution(target, dp[total]) for total in candidate_totals]
    exact = [solution for solution in solutions if solution["difference_mm"] <= tolerance_mm]
    ranked = sorted(exact or solutions, key=_rank_key)
    return ranked[:max_solutions]
