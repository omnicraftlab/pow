import os
from contextlib import contextmanager

import pytest

from pow_cli.common import prompt as prompt_module
from pow_cli.common.prompt import _path_completion, ask_choice, ask_path, complete_path


@pytest.fixture
def tree(tmp_path):
    """A small filesystem tree to complete against."""
    (tmp_path / "IsaacSim-ros_workspaces").mkdir()
    (tmp_path / "Isaac-other").mkdir()
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Isaac-notes.txt").write_text("")
    (tmp_path / ".hidden").mkdir()
    return tmp_path


# ── complete_path ───────────────────────────────────────────────────────────────

def test_completes_matching_prefix_only(tree):
    matches = complete_path(f"{tree}/Isaac")

    assert set(matches) == {
        f"{tree}/IsaacSim-ros_workspaces{os.sep}",
        f"{tree}/Isaac-other{os.sep}",
        f"{tree}/Isaac-notes.txt",
    }


def test_directories_get_trailing_separator(tree):
    matches = complete_path(f"{tree}/Projects")

    assert matches == [f"{tree}/Projects{os.sep}"]


def test_dirs_only_drops_files(tree):
    matches = complete_path(f"{tree}/Isaac", dirs_only=True)

    assert all(m.endswith(os.sep) for m in matches)
    assert not any("notes" in m for m in matches)


def test_hidden_entries_need_an_explicit_dot(tree):
    assert not any(".hidden" in m for m in complete_path(f"{tree}/"))
    assert complete_path(f"{tree}/.hid") == [f"{tree}/.hidden{os.sep}"]


def test_empty_prefix_lists_the_directory(tree):
    matches = complete_path(f"{tree}/")

    assert len(matches) == 4  # everything except .hidden
    assert matches == sorted(matches)


def test_no_match_returns_empty(tree):
    assert complete_path(f"{tree}/nope") == []


def test_tilde_is_preserved_in_matches(tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree))

    matches = complete_path("~/IsaacSim")

    assert matches == [f"~/IsaacSim-ros_workspaces{os.sep}"]


def test_tilde_completion_is_dirs_only_aware(tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree))

    assert complete_path("~/Isaac", dirs_only=True) == [
        f"~/Isaac-other{os.sep}",
        f"~/IsaacSim-ros_workspaces{os.sep}",
    ]


# ── the installed readline completer ────────────────────────────────────────────

@pytest.fixture
def completer(tree):
    """The (text, state) callable readline sees, for a dirs-only prompt."""
    readline = pytest.importorskip("readline")
    with _path_completion(dirs_only=True) as active:
        if not active:
            pytest.skip("readline unavailable")
        yield readline.get_completer()


def _all_states(completer, text):
    out = []
    state = 0
    while (match := completer(text, state)) is not None:
        out.append(match)
        state += 1
    return out


def test_completer_duplicates_a_unique_directory(completer, tree):
    """A duplicate stops readline appending a space, so typing can continue."""
    result = _all_states(completer, f"{tree}/Projec")

    assert result == [f"{tree}/Projects{os.sep}"] * 2


def test_completer_completes_into_a_directory(completer, tree):
    """Completing "dir/" offers its children, so a match never equals the input."""
    (tree / "Projects" / "sub").mkdir()

    assert _all_states(completer, f"{tree}/Projects{os.sep}") == [
        f"{tree}/Projects/sub{os.sep}"
    ] * 2


def test_completer_does_not_duplicate_a_unique_file(tree):
    """A file keeps readline's trailing space, which is the shell behaviour."""
    readline = pytest.importorskip("readline")
    with _path_completion(dirs_only=False) as active:
        if not active:
            pytest.skip("readline unavailable")
        assert _all_states(readline.get_completer(), f"{tree}/Isaac-not") == [
            f"{tree}/Isaac-notes.txt"
        ]


def test_completer_returns_every_ambiguous_match(completer, tree):
    result = _all_states(completer, f"{tree}/Isaac")

    assert result == [f"{tree}/Isaac-other{os.sep}", f"{tree}/IsaacSim-ros_workspaces{os.sep}"]


def test_completer_absorbs_a_trailing_space(completer, tree):
    """A space readline appended earlier must not break the next completion."""
    assert _all_states(completer, f"{tree}/Projec ") == [f"{tree}/Projects{os.sep}"] * 2


def test_completer_returns_nothing_when_no_match(completer, tree):
    assert _all_states(completer, f"{tree}/nope") == []


def test_completer_uses_line_wide_delimiters(tree):
    """Default delims split on "/" and "~", which would break path completion."""
    readline = pytest.importorskip("readline")
    with _path_completion() as active:
        if not active:
            pytest.skip("readline unavailable")
        assert readline.get_completer_delims() == "\n"


# ── ask_path ────────────────────────────────────────────────────────────────────

def test_ask_path_strips_whitespace_and_trailing_separator(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "  ~/ws/  ")

    assert ask_path("Path", default="~/default") == "~/ws"


def test_ask_path_keeps_root_separator(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "/")

    assert ask_path("Path", default="~/default") == "/"


def test_ask_path_empty_input_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert ask_path("Path", default="~/IsaacSim-ros_workspaces") == "~/IsaacSim-ros_workspaces"


def test_ask_path_restores_readline_state(monkeypatch):
    readline = pytest.importorskip("readline")

    def sentinel_completer(text, state):  # pragma: no cover - never called
        return None

    readline.set_completer(sentinel_completer)
    readline.set_completer_delims(" \t\n")
    monkeypatch.setattr("builtins.input", lambda prompt="": "~/ws")

    ask_path("Path", default="~/default")

    assert readline.get_completer() is sentinel_completer
    assert readline.get_completer_delims() == " \t\n"


def test_ask_path_prompt_is_passed_to_input(monkeypatch):
    """readline needs the prompt to redraw the line, so input() must receive it."""
    seen = {}

    def fake_input(prompt=""):
        seen["prompt"] = prompt
        return "~/ws"

    monkeypatch.setattr("builtins.input", fake_input)

    ask_path("Path to clone", default="~/IsaacSim-ros_workspaces")

    assert "Path to clone" in seen["prompt"]
    assert "~/IsaacSim-ros_workspaces" in seen["prompt"]


# ── ask_choice ──────────────────────────────────────────────────────────────────

CHOICES = [("6.1.0", "latest"), ("5.1.0", "installed")]


@pytest.fixture
def keys(monkeypatch):
    """Drive the picker from a scripted key sequence."""
    def script(*presses):
        pressed = iter(presses)
        monkeypatch.setattr(prompt_module, "_is_interactive", lambda: True)
        monkeypatch.setattr(prompt_module, "_cbreak_mode", _noop_cbreak)
        monkeypatch.setattr(prompt_module, "_read_key", lambda _fd: next(pressed))
    return script


@contextmanager
def _noop_cbreak():
    """Stand in for the real termios juggling, which needs a tty."""
    yield 0


def test_ask_choice_returns_default_on_enter(keys):
    keys("enter")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "6.1.0"


def test_ask_choice_starts_the_cursor_on_the_default(keys):
    """Enter with no movement returns the default, not the first entry."""
    keys("enter")

    assert ask_choice("Pick", CHOICES, default="5.1.0") == "5.1.0"


def test_ask_choice_moves_down(keys):
    keys("down", "enter")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "5.1.0"


def test_ask_choice_wraps_around_both_ends(keys):
    keys("up", "enter")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "5.1.0"

    keys("down", "down", "enter")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "6.1.0"


def test_ask_choice_ignores_unknown_keys(keys):
    keys("", "down", "", "enter")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "5.1.0"


def test_ask_choice_aborts(keys):
    keys("abort")

    with pytest.raises(KeyboardInterrupt):
        ask_choice("Pick", CHOICES, default="6.1.0")


def test_ask_choice_restores_the_cursor_after_an_abort(keys, mocker):
    """An abort must not leave the terminal without a cursor."""
    keys("abort")
    show_cursor = mocker.patch.object(prompt_module.console, "show_cursor")

    with pytest.raises(KeyboardInterrupt):
        ask_choice("Pick", CHOICES, default="6.1.0")

    assert show_cursor.call_args_list[-1].args == (True,)


def test_ask_choice_unknown_default_starts_at_the_first_entry(keys):
    keys("enter")

    assert ask_choice("Pick", CHOICES, default="9.9.9") == "6.1.0"


def test_ask_choice_rejects_an_empty_choice_list():
    with pytest.raises(ValueError):
        ask_choice("Pick", [])


# ── ask_choice: non-interactive fallback ────────────────────────────────────────

def test_ask_choice_falls_back_to_a_typed_prompt(monkeypatch):
    """Piped stdin / CI / the click runner must not hit the raw-terminal path."""
    monkeypatch.setattr(prompt_module, "_is_interactive", lambda: False)

    def boom(_fd):  # pragma: no cover - the point is that it is never reached
        raise AssertionError("_read_key must not run without a terminal")

    monkeypatch.setattr(prompt_module, "_read_key", boom)
    monkeypatch.setattr("builtins.input", lambda prompt="": "5.1.0")

    assert ask_choice("Pick", CHOICES, default="6.1.0") == "5.1.0"


def test_ask_choice_fallback_offers_values_in_display_order(monkeypatch, mocker):
    monkeypatch.setattr(prompt_module, "_is_interactive", lambda: False)
    ask = mocker.patch.object(prompt_module.Prompt, "ask", return_value="6.1.0")

    ask_choice("Pick", CHOICES, default="6.1.0")

    assert ask.call_args.kwargs["choices"] == ["6.1.0", "5.1.0"]
    assert ask.call_args.kwargs["default"] == "6.1.0"


# ── ask_choice: key decoding ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sequence,expected",
    [
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1bOA", "up"),
        (b"\x1bOB", "down"),
        (b"\r", "enter"),
        (b"\n", "enter"),
        (b"k", "up"),
        (b"j", "down"),
        (b"\x03", "abort"),
        (b"\x04", "abort"),
        (b"\x1b", "abort"),
        (b"q", "abort"),
        (b"z", ""),
        (b"\x1b[C", ""),
    ],
)
def test_read_key_decodes_sequences(sequence, expected, monkeypatch):
    """An escape sequence arrives as one read, so Esc is unambiguous."""
    monkeypatch.setattr(prompt_module.os, "read", lambda _fd, _n: sequence)

    assert prompt_module._read_key(0) == expected


def test_read_key_treats_eof_as_abort(monkeypatch):
    """A vanished terminal must abort, not spin on empty reads."""
    monkeypatch.setattr(prompt_module.os, "read", lambda _fd, _n: b"")

    assert prompt_module._read_key(0) == "abort"
