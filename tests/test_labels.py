from docrecorder.capture.base import WindowInfo
from docrecorder.labels import unique_labels


def _window(title: str, app: str, width: int, window_id: int = 1) -> WindowInfo:
    return WindowInfo(
        window_id=window_id,
        title=title,
        app_name=app,
        pid=1,
        x=0,
        y=0,
        width=width,
        height=400,
    )


def test_unique_labels_disambiguate_duplicates():
    windows = [
        _window("Inbox", "Mail", 800, 1),
        _window("Inbox", "Mail", 1024, 2),
        _window("Notes", "Notes", 600, 3),
    ]
    labels = unique_labels(windows)
    assert labels[0] != labels[1]
    assert "800×400" in labels[0] or "800×400" in labels[1]
    assert labels[2] == "Notes"
    assert len(set(labels)) == 3
