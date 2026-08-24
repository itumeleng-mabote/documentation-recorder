from docrecorder.typing_buffer import TypingBuffer


def test_push_and_flush_text():
    buffer = TypingBuffer(idle_seconds=1.5)
    buffer.push_char("h", 0.0)
    buffer.push_char("i", 0.1)
    assert buffer.text == "hi"
    assert buffer.flush() == "hi"
    assert buffer.flush() is None
    assert not buffer.has_text()


def test_backspace_edits_buffer():
    buffer = TypingBuffer()
    buffer.push_char("a", 0.0)
    buffer.push_char("b", 0.1)
    buffer.backspace(0.2)
    buffer.push_char("c", 0.3)
    assert buffer.flush() == "ac"


def test_idle_due_after_timeout():
    buffer = TypingBuffer(idle_seconds=1.5)
    buffer.push_char("x", 1.0)
    assert not buffer.idle_due(2.0)
    assert buffer.idle_due(2.5)
    buffer.flush()
    assert not buffer.idle_due(10.0)


def test_backspace_on_empty_is_safe():
    buffer = TypingBuffer()
    buffer.backspace(0.0)
    assert buffer.flush() is None
