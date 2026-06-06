from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..config import settings
from .feature_matching import FeatureSet, PairMatch

LogFn = Callable[[str], None]


@dataclass(slots=True)
class AlignmentResult:
    transforms: list[np.ndarray]
    root_index: int
    tree_edges: list[PairMatch]
    optimized: bool
    rms_error: float | None


def _noop(_: str) -> None:
    return


def _maximum_spanning_tree(edges: list[PairMatch], count: int) -> list[PairMatch]:
    parent = list(range(count))
    rank = [0] * count

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> bool:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return False
        if rank[root_left] < rank[root_right]:
            parent[root_left] = root_right
        elif rank[root_left] > rank[root_right]:
            parent[root_right] = root_left
        else:
            parent[root_right] = root_left
            rank[root_left] += 1
        return True

    tree: list[PairMatch] = []
    for edge in sorted(edges, key=lambda item: (item.score, item.inliers), reverse=True):
        if union(edge.left, edge.right):
            tree.append(edge)
            if len(tree) == count - 1:
                break
    return tree


def _initial_transforms_from_tree(tree: list[PairMatch], count: int) -> tuple[list[np.ndarray], int]:
    adjacency: list[list[tuple[int, np.ndarray, float]]] = [[] for _ in range(count)]
    strength = [0.0] * count
    for edge in tree:
        inverse = np.linalg.inv(edge.h_left_to_right)
        adjacency[edge.left].append((edge.right, edge.h_left_to_right, edge.score))
        adjacency[edge.right].append((edge.left, inverse, edge.score))
        strength[edge.left] += edge.score
        strength[edge.right] += edge.score

    root = max(range(count), key=lambda idx: strength[idx])
    transforms: list[np.ndarray | None] = [None] * count
    transforms[root] = np.eye(3, dtype=np.float64)
    queue = [root]

    for current in queue:
        current_to_global = transforms[current]
        if current_to_global is None:
            continue
        for neighbor, current_to_neighbor, _ in adjacency[current]:
            if transforms[neighbor] is not None:
                continue
            transforms[neighbor] = current_to_global @ np.linalg.inv(current_to_neighbor)
            queue.append(neighbor)

    if any(matrix is None for matrix in transforms):
        raise RuntimeError("Alignment graph is disconnected.")
    return [matrix for matrix in transforms if matrix is not None], root


def _unknown_index(image_index: int, root_index: int) -> int | None:
    if image_index == root_index:
        return None
    return image_index if image_index < root_index else image_index - 1


def _add_affine_terms(row: np.ndarray, image_index: int, x: float, y: float, axis: int, sign: float, root_index: int):
    unknown = _unknown_index(image_index, root_index)
    if unknown is None:
        return np.array([x, y, 1.0] if axis == 0 else [0.0, 0.0, 0.0], dtype=np.float64)

    base = unknown * 6
    if axis == 0:
        row[base : base + 3] += sign * np.array([x, y, 1.0], dtype=np.float64)
    else:
        row[base + 3 : base + 6] += sign * np.array([x, y, 1.0], dtype=np.float64)
    return None


def _sample_indices(total: int, limit: int) -> np.ndarray:
    if total <= limit:
        return np.arange(total)
    return np.linspace(0, total - 1, limit, dtype=np.int64)


def _optimize_affine_transforms(edges: list[PairMatch], count: int, root_index: int) -> tuple[list[np.ndarray], float]:
    variables = (count - 1) * 6
    if variables <= 0:
        return [np.eye(3, dtype=np.float64)], 0.0

    rows = []
    rhs = []
    max_samples = max(20, int(settings.stitch_planar_max_match_samples))

    for edge in edges:
        indices = _sample_indices(len(edge.points_left), max_samples)
        weight = float(np.sqrt(max(edge.score, 1.0)))
        for idx in indices:
            left_x, left_y = edge.points_left[idx]
            right_x, right_y = edge.points_right[idx]

            row_x = np.zeros(variables, dtype=np.float64)
            root_left = _add_affine_terms(row_x, edge.left, left_x, left_y, 0, 1.0, root_index)
            root_right = _add_affine_terms(row_x, edge.right, right_x, right_y, 0, -1.0, root_index)
            target_x = 0.0
            if root_left is not None:
                target_x -= root_left[0]
            if root_right is not None:
                target_x += root_right[0]
            rows.append(row_x * weight)
            rhs.append(target_x * weight)

            row_y = np.zeros(variables, dtype=np.float64)
            root_left = _add_affine_terms(row_y, edge.left, left_x, left_y, 1, 1.0, root_index)
            root_right = _add_affine_terms(row_y, edge.right, right_x, right_y, 1, -1.0, root_index)
            target_y = 0.0
            if root_left is not None:
                target_y -= left_y
            if root_right is not None:
                target_y += right_y
            rows.append(row_y * weight)
            rhs.append(target_y * weight)

    if len(rows) < variables:
        raise RuntimeError("Not enough constraints for global affine optimization.")

    matrix = np.vstack(rows)
    vector = np.asarray(rhs, dtype=np.float64)
    solution, _, _, _ = np.linalg.lstsq(matrix, vector, rcond=None)

    transforms = []
    for image_index in range(count):
        unknown = _unknown_index(image_index, root_index)
        if unknown is None:
            transforms.append(np.eye(3, dtype=np.float64))
            continue
        values = solution[unknown * 6 : unknown * 6 + 6]
        transforms.append(
            np.array(
                [
                    [values[0], values[1], values[2]],
                    [values[3], values[4], values[5]],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )
        )

    residuals = []
    for edge in edges:
        indices = _sample_indices(len(edge.points_left), max_samples)
        left_h = np.c_[edge.points_left[indices], np.ones(len(indices))]
        right_h = np.c_[edge.points_right[indices], np.ones(len(indices))]
        projected_left = (transforms[edge.left] @ left_h.T).T[:, :2]
        projected_right = (transforms[edge.right] @ right_h.T).T[:, :2]
        residuals.extend(np.linalg.norm(projected_left - projected_right, axis=1).tolist())
    rms = float(np.sqrt(np.mean(np.square(residuals)))) if residuals else 0.0
    return transforms, rms


def align_global(features: list[FeatureSet], pair_matches: list[PairMatch], log: LogFn = _noop) -> AlignmentResult:
    count = len(features)
    if len(pair_matches) < count - 1:
        raise RuntimeError(
            f"Only {len(pair_matches)} reliable overlaps found for {count} images. "
            "Increase overlap between images or use panorama mode."
        )

    tree = _maximum_spanning_tree(pair_matches, count)
    if len(tree) < count - 1:
        raise RuntimeError("Images do not form one connected overlap graph.")

    initial_transforms, root = _initial_transforms_from_tree(tree, count)
    log(f"[align] root={root}, pair_edges={len(pair_matches)}, tree_edges={len(tree)}")

    model = str(settings.stitch_planar_transform_model).lower()
    if model == "homography" or not bool(settings.stitch_planar_global_optimize):
        log("[align] using spanning-tree homography accumulation")
        return AlignmentResult(initial_transforms, root, tree, optimized=False, rms_error=None)

    try:
        transforms, rms = _optimize_affine_transforms(pair_matches, count, root)
        log(f"[align] global affine optimization rms={rms:.3f}px")
        return AlignmentResult(transforms, root, tree, optimized=True, rms_error=rms)
    except Exception as exc:
        log(f"[align] global optimization failed; using tree transforms. reason={exc}")
        return AlignmentResult(initial_transforms, root, tree, optimized=False, rms_error=None)
