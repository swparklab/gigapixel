from app.services.acquisition import build_acquisition_plan, build_acquisition_scenario


def test_r8_reference_counts_for_yesterday_size():
    common = {
        "camera_width": 6000,
        "camera_height": 4000,
        "target_width": 18000,
        "target_height": 12000,
        "focus_stack_shots": 1,
        "safe_shots_per_battery": 250,
    }

    assert build_acquisition_scenario(overlap_percent=60, **common).positions == 36
    assert build_acquisition_scenario(overlap_percent=70, **common).positions == 64
    assert build_acquisition_scenario(overlap_percent=80, **common).positions == 121


def test_r8_reference_counts_for_30k_square():
    common = {
        "camera_width": 6000,
        "camera_height": 4000,
        "target_width": 30000,
        "target_height": 30000,
        "focus_stack_shots": 1,
        "safe_shots_per_battery": 250,
    }

    assert build_acquisition_scenario(overlap_percent=60, **common).positions == 198
    assert build_acquisition_scenario(overlap_percent=70, **common).positions == 345
    assert build_acquisition_scenario(overlap_percent=80, **common).positions == 714


def test_depth_stack_and_battery_estimate():
    plan = build_acquisition_plan(
        camera_width=6000,
        camera_height=4000,
        target_width=30000,
        target_height=30000,
        overlap_percent=80,
        focus_stack_shots=6,
        safe_shots_per_battery=250,
    )

    assert plan.selected.positions == 714
    assert plan.selected.captures == 4284
    assert plan.selected.batteries == 18

