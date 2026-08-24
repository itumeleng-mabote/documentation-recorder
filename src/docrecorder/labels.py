from __future__ import annotations

from docrecorder.capture.base import WindowInfo


def unique_labels(windows: list[WindowInfo]) -> list[str]:
    counts: dict[str, int] = {}
    for window in windows:
        counts[window.label] = counts.get(window.label, 0) + 1
    labels: list[str] = []
    used: set[str] = set()
    for window in windows:
        label = window.label
        if counts[label] > 1:
            label = f"{label} ({int(window.width)}×{int(window.height)})"
        original = label
        suffix = 2
        while label in used:
            label = f"{original} #{suffix}"
            suffix += 1
        used.add(label)
        labels.append(label)
    return labels
