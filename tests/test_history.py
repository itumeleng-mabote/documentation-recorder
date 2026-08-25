from docrecorder.history import EditHistory


def _steps(*captions: str) -> list[dict]:
    return [{"caption": caption} for caption in captions]


def test_undo_restores_previous_snapshot():
    history = EditHistory()
    history.push(_steps("one"))
    restored = history.undo(_steps("two"))
    assert restored == _steps("one")
    assert not history.can_undo()
    assert history.can_redo()


def test_redo_restores_undone_snapshot():
    history = EditHistory()
    history.push(_steps("one"))
    history.undo(_steps("two"))
    restored = history.redo(_steps("one"))
    assert restored == _steps("two")
    assert history.can_undo()
    assert not history.can_redo()


def test_push_clears_redo():
    history = EditHistory()
    history.push(_steps("one"))
    history.undo(_steps("two"))
    history.push(_steps("three"))
    assert not history.can_redo()
    assert history.undo(_steps("four")) == _steps("three")


def test_push_skips_duplicate_consecutive_state():
    history = EditHistory()
    history.push(_steps("one"))
    history.push(_steps("one"))
    assert history.undo(_steps("two")) == _steps("one")
    assert history.undo(_steps("one")) is None


def test_history_respects_limit():
    history = EditHistory(limit=2)
    history.push(_steps("a"))
    history.push(_steps("b"))
    history.push(_steps("c"))
    assert history.undo(_steps("d")) == _steps("c")
    assert history.undo(_steps("c")) == _steps("b")
    assert history.undo(_steps("b")) is None
