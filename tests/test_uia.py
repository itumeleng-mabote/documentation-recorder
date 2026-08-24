from docrecorder.capture.uia_windows import CONTROL_TYPE_KINDS, ElementProbe
from docrecorder.vision import VALID_KINDS


def test_control_type_kinds_use_known_vocabulary():
    assert set(CONTROL_TYPE_KINDS.values()) <= VALID_KINDS


def test_probe_disables_itself_after_failure(monkeypatch):
    probe = ElementProbe()
    probe.enabled = True
    monkeypatch.setattr(
        "docrecorder.capture.uia_windows.element_at_point",
        lambda _x, _y: (_ for _ in ()).throw(RuntimeError("com error")),
    )
    assert probe.lookup(10, 10) is None
    assert probe.enabled is False
    assert probe.warning


def test_probe_returns_target(monkeypatch):
    probe = ElementProbe()
    probe.enabled = True
    monkeypatch.setattr(
        "docrecorder.capture.uia_windows.element_at_point",
        lambda _x, _y: {"label": "annotated", "kind": "item", "source": "uia"},
    )
    assert probe.lookup(10, 10) == {"label": "annotated", "kind": "item", "source": "uia"}
    assert probe.enabled is True


def test_probe_disabled_short_circuits():
    probe = ElementProbe()
    probe.enabled = False
    assert probe.lookup(10, 10) is None
