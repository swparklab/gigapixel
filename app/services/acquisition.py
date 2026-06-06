from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcquisitionScenario:
    overlap_percent: float
    columns: int
    rows: int
    positions: int
    captures: int
    coverage_width: int
    coverage_height: int
    step_x: float
    step_y: float
    batteries: int


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    camera_width: int
    camera_height: int
    target_width: int
    target_height: int
    focus_stack_shots: int
    safe_shots_per_battery: int
    selected: AcquisitionScenario
    scenarios: list[AcquisitionScenario]
    recommendation: str


def _tile_count(target_size: int, frame_size: int, overlap_percent: float) -> tuple[int, float, int]:
    if target_size <= 0 or frame_size <= 0:
        raise ValueError("Image dimensions must be positive.")
    if overlap_percent < 0 or overlap_percent >= 100:
        raise ValueError("Overlap must be in the range [0, 100).")

    step = frame_size * (1.0 - overlap_percent / 100.0)
    if target_size <= frame_size:
        return 1, step, frame_size

    # Avoid one-extra tile from values like 6000 * 0.2 == 1199.9999999999998.
    count = int(math.ceil(((target_size - frame_size) / step) - 1e-9) + 1)
    coverage = int(math.ceil(frame_size + (count - 1) * step))
    return count, step, coverage


def build_acquisition_scenario(
    *,
    camera_width: int,
    camera_height: int,
    target_width: int,
    target_height: int,
    overlap_percent: float,
    focus_stack_shots: int,
    safe_shots_per_battery: int,
) -> AcquisitionScenario:
    if focus_stack_shots < 1:
        raise ValueError("Focus stack shots must be at least 1.")
    if safe_shots_per_battery < 1:
        raise ValueError("Safe shots per battery must be at least 1.")

    columns, step_x, coverage_width = _tile_count(target_width, camera_width, overlap_percent)
    rows, step_y, coverage_height = _tile_count(target_height, camera_height, overlap_percent)
    positions = columns * rows
    captures = positions * focus_stack_shots
    batteries = int(math.ceil(captures / safe_shots_per_battery))
    return AcquisitionScenario(
        overlap_percent=overlap_percent,
        columns=columns,
        rows=rows,
        positions=positions,
        captures=captures,
        coverage_width=coverage_width,
        coverage_height=coverage_height,
        step_x=step_x,
        step_y=step_y,
        batteries=batteries,
    )


def build_acquisition_plan(
    *,
    camera_width: int = 6000,
    camera_height: int = 4000,
    target_width: int = 30000,
    target_height: int = 30000,
    overlap_percent: float = 80.0,
    focus_stack_shots: int = 6,
    safe_shots_per_battery: int = 250,
) -> AcquisitionPlan:
    checkpoints = sorted({0.0, 60.0, 70.0, 80.0, float(overlap_percent)})
    scenarios = [
        build_acquisition_scenario(
            camera_width=camera_width,
            camera_height=camera_height,
            target_width=target_width,
            target_height=target_height,
            overlap_percent=value,
            focus_stack_shots=focus_stack_shots,
            safe_shots_per_battery=safe_shots_per_battery,
        )
        for value in checkpoints
    ]
    selected = next(item for item in scenarios if item.overlap_percent == float(overlap_percent))
    recommendation = (
        f"{selected.overlap_percent:.0f}% overlap requires {selected.columns} x {selected.rows} = "
        f"{selected.positions} positions. With {focus_stack_shots} focus-stack shots per position, "
        f"capture {selected.captures} total frames and prepare at least {selected.batteries} batteries "
        f"at {safe_shots_per_battery} safe shots per battery."
    )
    return AcquisitionPlan(
        camera_width=camera_width,
        camera_height=camera_height,
        target_width=target_width,
        target_height=target_height,
        focus_stack_shots=focus_stack_shots,
        safe_shots_per_battery=safe_shots_per_battery,
        selected=selected,
        scenarios=scenarios,
        recommendation=recommendation,
    )
