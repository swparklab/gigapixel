"""Acquisition coverage QA.

Before committing to a long stitch, check whether a captured set actually
overlaps enough to register: builds the same overlap graph the stitcher uses,
reports each image's neighbour count, flags weakly/non-overlapping images, and
detects whether the set forms a single connected component (a hard requirement
for a single mosaic). Returns actionable recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import settings
from .feature_matching import build_feature_sets, estimate_pair_matches, validate_image_set

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class CoverageReport:
    image_count: int
    pair_count: int
    connected: bool
    components: int
    verdict: str = "ok"  # ok | warn | broken
    weak_images: list[dict] = field(default_factory=list)
    isolated_images: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "image_count": self.image_count,
            "pair_count": self.pair_count,
            "connected": self.connected,
            "components": self.components,
            "verdict": self.verdict,
            "weak_images": self.weak_images,
            "isolated_images": self.isolated_images,
            "recommendations": self.recommendations,
        }


def _components(count: int, edges: list[tuple[int, int]]) -> list[set[int]]:
    parent = list(range(count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[int, set[int]] = {}
    for i in range(count):
        groups.setdefault(find(i), set()).add(i)
    return list(groups.values())


def analyze_coverage(image_paths: list[Path], log: LogFn = _noop) -> CoverageReport:
    infos = validate_image_set(image_paths, log)
    count = len(infos)
    features = build_feature_sets(image_paths, log)
    pairs = estimate_pair_matches(features, log, image_paths=image_paths)

    min_inliers = int(settings.coverage_min_overlap_inliers)
    edges = [(p.left, p.right) for p in pairs if p.inliers >= min_inliers]
    degree = [0] * count
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    comps = _components(count, edges)
    connected = len(comps) == 1

    report = CoverageReport(image_count=count, pair_count=len(edges), connected=connected, components=len(comps))
    names = [Path(p).name for p in image_paths]
    for i in range(count):
        if degree[i] == 0:
            report.isolated_images.append(names[i])
        elif degree[i] == 1:
            report.weak_images.append({"image": names[i], "overlaps": degree[i]})

    if report.isolated_images or not connected:
        report.verdict = "broken"
        report.recommendations.append(
            "Set is not a single connected overlap graph; re-shoot bridging frames or increase overlap to ~70-80%."
        )
    elif report.weak_images:
        report.verdict = "warn"
        report.recommendations.append(
            "Some images overlap only one neighbour; add frames around them for robust global alignment."
        )
    else:
        report.recommendations.append("Overlap graph is healthy and fully connected.")

    log(f"[coverage] verdict={report.verdict} pairs={len(edges)} components={len(comps)}")
    return report
