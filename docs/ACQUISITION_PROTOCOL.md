# Acquisition Protocol

Last updated: 2026-06-06

## Problem Definition

The acquisition problem is not only "how many images are needed." It is a combined planning problem:

- Target mosaic resolution.
- Camera frame resolution.
- Required overlap for reliable stitching.
- Focus-stack count per camera position.
- Battery and storage capacity.
- Lighting quality and shadow suppression.
- Post-PTGui cleanup such as frame removal and non-destructive seam correction.

The immediate research target is Canon R8-based capture for cultural heritage works, where quality is prioritized over minimum capture count.

## Camera Assumption

Default camera frame:

- Canon R8 full-frame capture: `6000 x 4000 px`

Default quality setting:

- Overlap: `80%`
- Focus stacking: `5-6 shots per position`
- Safe shots per battery, based on current field observation: `250 shots`

## Capture Count Formula

Let:

- `Wc`, `Hc` = camera image width and height.
- `Wt`, `Ht` = target mosaic width and height.
- `o` = overlap fraction, for example `0.8` for 80%.
- `sx = Wc * (1 - o)` = horizontal movement step.
- `sy = Hc * (1 - o)` = vertical movement step.

Then:

```text
columns = ceil((Wt - Wc) / sx) + 1
rows    = ceil((Ht - Hc) / sy) + 1
positions = columns * rows
total_captures = positions * focus_stack_shots
batteries = ceil(total_captures / safe_shots_per_battery)
```

If the target dimension is smaller than one camera frame, that axis uses one tile.

## Canon R8 Reference Table

### Target: 18,000 x 12,000

| Overlap | Grid | Camera positions | 5-shot focus stack | 6-shot focus stack |
| --- | --- | ---: | ---: | ---: |
| 0% | 3 x 3 | 9 | 45 | 54 |
| 60% | 6 x 6 | 36 | 180 | 216 |
| 70% | 8 x 8 | 64 | 320 | 384 |
| 80% | 11 x 11 | 121 | 605 | 726 |

Interpretation:

- The previous 56-image stitching experiment is between the 60% and 70% single-shot planning range.
- If focus stacking is added, the total number of exposures increases by the stack count.

### Target: 30,000 x 30,000

| Overlap | Grid | Camera positions | 5-shot focus stack | 6-shot focus stack |
| --- | --- | ---: | ---: | ---: |
| 0% | 5 x 8 | 40 | 200 | 240 |
| 60% | 11 x 18 | 198 | 990 | 1,188 |
| 70% | 15 x 23 | 345 | 1,725 | 2,070 |
| 80% | 21 x 34 | 714 | 3,570 | 4,284 |

Interpretation:

- At the requested 80% overlap and 6-shot focus stacking, a 30k x 30k target requires 4,284 exposures.
- With a conservative 250 shots per battery, prepare at least 18 batteries or an equivalent external power strategy.

## Recommended Field Protocol

### For quality-first acquisition

- Use 80% overlap.
- Use focus stacking at 5-6 shots per position.
- Keep exposure, white balance, ISO, aperture, and shutter speed fixed manually.
- Use stable, repeatable camera movement.
- Capture row/column order consistently.
- Add calibration shots when possible.

### For lighting

- Use diffuse, symmetric lighting.
- Avoid side-cast shadows from camera rig, frame edge, or operator.
- Confirm shadow absence with a test stitch before full acquisition.
- Keep illumination stable across the entire scan.

### For focus stacking

- Treat one camera position as a stack group.
- Capture all focus depths before moving to the next grid position.
- Preserve deterministic filenames so stack groups can be reconstructed.
- Future software support should model one logical tile position with multiple source frames.

## Post-PTGui Cleanup Requirements

Professor request:

- Remove wooden frame area from the PTGui-stitched output.
- Apply non-destructive correction for subtle step or seam artifacts.

Implementation direction:

- Add a post-processing stage after raw stitch output and before final export.
- Keep the original BigTIFF unchanged.
- Save corrected outputs as derived artifacts.
- Prefer mask/crop metadata and pixel-preserving transforms over destructive edits.
- Record every correction as structured metadata for reproducibility.

Suggested stages:

```text
stitched_raw.tif
  -> frame mask or crop boundary detection
  -> artwork-only BigTIFF export
  -> local seam/step correction mask
  -> corrected BigTIFF export
  -> optimized JPEG and DZI generation
```

## Software Support Added

The application now includes:

- `POST /api/acquisition/plan`
- Classic UI acquisition planner
- Unit tests that verify the Canon R8 reference counts from the research discussion

