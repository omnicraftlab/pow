"""The ``.vscode/settings.json`` settings ``pow init`` owns, and how it applies them.

``pow init`` used to copy Isaac Sim's own ``settings.json`` over the project's
file, which destroyed anything the user had added to it.  Instead, the keys
below are treated as *pow-managed*: they are written on every init, and every
other key in the file - along with its comments and formatting - is left alone.

``python.analysis.extraPaths`` is not listed here because it is version
specific.  It is read from the ``settings.json`` of the Isaac Sim install init
selected and re-pointed at ``_isaacsim/``, so a 5.1.0 and a 6.1.0 project each
get that version's extension list - the two differ in their extensions and in the
``kit/python/lib/python3.X`` entries, so a list from the wrong version leaves
every Isaac import unresolved.  It is rewritten only when init changes the
project's Isaac Sim version (see ``replace_extra_paths`` in :func:`apply`);
otherwise the project keeps the list it has.
"""

import copy
import json
from pathlib import Path

from ..common import jsonc

#: Name of the symlink `pow init` creates for the managed Isaac Sim install.
LINK_NAME = "_isaacsim"

EXTRA_PATHS_KEY = "python.analysis.extraPaths"

#: Keys pow writes, in the order a freshly created file lists them.  The
#: ``None`` for :data:`EXTRA_PATHS_KEY` is a placeholder marking its position;
#: :func:`managed_settings` fills it in or drops it.
MANAGED_SETTINGS = {
    # Keeping the extension host off _isaacsim is what makes the editor usable:
    # see PERFORMANCE_NOTE below.
    "files.watcherExclude": {
        "**/.git/objects/**": True,
        "**/.git/subtree-cache/**": True,
        "**/.venv/**": True,
        f"**/{LINK_NAME}/**": True,
        "**/_out_*/**": True,
        "**/__pycache__/**": True,
        "**/.vscode/browse.vc.db*": True,
    },
    "search.exclude": {
        "**/.venv": True,
        f"**/{LINK_NAME}": True,
        "**/_out_*": True,
        "**/__pycache__": True,
    },
    "search.followSymlinks": False,
    "files.exclude": {
        "**/__pycache__": True,
        "**/*.pyc": True,
    },
    "python.analysis.exclude": [
        "**/.venv/**",
        f"{LINK_NAME}/**",
        "_out_*/**",
        "**/__pycache__/**",
    ],
    "taskexplorer.useVscWatcherExclude": True,
    "taskexplorer.exclude": [
        "**/.venv/**",
        f"**/{LINK_NAME}/**",
        "**/_out_*/**",
        "**/__pycache__/**",
        "**/node_modules/**",
        "**/dist/**",
        "**/out/**",
        "**/build/**",
        "**/.git*/**",
        "**/doc{,s,umentation}/**",
        "**/{img,image,images,ico,icon,icons}/**",
        "**/*asset{,s}/**",
    ],
    "taskexplorer.enablePersistentFileCaching": True,
    "editor.rulers": [120],
    "js/ts.tsc.autoDetect": "off",
    "grunt.autoDetect": "off",
    "jake.autoDetect": "off",
    "gulp.autoDetect": "off",
    "npm.autoDetect": "off",
    "spellright.language": ["en"],
    "spellright.documentTypes": ["markdown", "latex", "plaintext", "cpp", "asciidoc"],
    "python.jediEnabled": False,
    EXTRA_PATHS_KEY: None,
    "python.languageServer": "Pylance",
    "python.defaultInterpreterPath": f"{LINK_NAME}/kit/python/bin/python3",
    "python.formatting.provider": "black",
    "python.formatting.blackArgs": ["--line-length", "120"],
    "python.linting.pylintEnabled": False,
    "python.linting.flake8Enabled": True,
    "ROS2.distro": "humble",
}

#: Container keys: pow makes sure its own entries are there and keeps whatever
#: else the project put in them.  Replacing these wholesale would throw away
#: excludes the user added by hand.
MERGED_KEYS = frozenset({
    "files.watcherExclude",
    "search.exclude",
    "files.exclude",
    "python.analysis.exclude",
    "taskexplorer.exclude",
})

#: Keys pow seeds but never overrides.  A project that points the interpreter at
#: its own .venv has made a deliberate choice; init must not undo it on every run.
SEEDED_KEYS = frozenset({"python.defaultInterpreterPath"})

#: Keys VSCode has renamed.  Removed when found, so the file does not keep both.
DEPRECATED_KEYS = ("typescript.tsc.autoDetect",)

PERFORMANCE_NOTE = f"""\
// ---------------------------------------------------------------------
// Performance: keep the extension host off .venv / {LINK_NAME} / _out_*.
// {LINK_NAME} is a symlink to a multi-GB Isaac Sim install (tens of
// thousands of .py files) that lives inside the workspace root.  Without
// these, every file create/rename triggers a workspace-wide rescan and the
// "Running 'File Create'/'File Rename' participants..." notification.
// ---------------------------------------------------------------------"""

#: Comments written above a key, only when pow creates the file from scratch.
#: A comment may span several lines.
LEADING_COMMENTS = {
    "files.watcherExclude": PERFORMANCE_NOTE,
    "python.analysis.exclude": (
        f"// Pylance: {LINK_NAME} stays an import-resolution root via\n"
        "// python.analysis.extraPaths below, but must not be parsed as workspace\n"
        '// source (pyright\'s default excludes skip ".*" dirs, not "_*").'
    ),
    "taskexplorer.useVscWatcherExclude": (
        "// Task Explorer rebuilds its file cache synchronously on the extension\n"
        "// host main thread on every create; its defaults ignore\n"
        f"// files.watcherExclude and do not cover .venv / {LINK_NAME}."
    ),
    "python.jediEnabled": (
        "// This enables python language server. Seems to work slightly better than jedi:"
    ),
    EXTRA_PATHS_KEY: (
        "// Filled by `pow init` from the Isaac Sim version this project is linked to:"
    ),
    "python.formatting.provider": '// We use "black" as a formatter:',
    "python.linting.pylintEnabled": "// Use flake8 for linting",
}

INDENT = 4


def managed_settings(extra_paths: list[str] | None = None) -> dict:
    """The full managed block, with *extra_paths* filled in when available."""
    settings = {}
    for key, value in MANAGED_SETTINGS.items():
        if key == EXTRA_PATHS_KEY:
            if extra_paths is not None:
                settings[key] = list(extra_paths)
        else:
            settings[key] = copy.deepcopy(value)
    return settings


def extra_paths(src_settings: Path) -> list[str] | None:
    """Read ``python.analysis.extraPaths`` from Isaac Sim's own settings.json.

    Each entry is re-pointed at the project's ``_isaacsim`` symlink, which is
    where Isaac Sim lives as far as the project is concerned.

    Returns None when the source file is missing, unreadable or does not carry
    the key - the caller then leaves the key untouched rather than failing the
    whole step.
    """
    try:
        text = src_settings.read_text()
        entries, _ = jsonc.scan_top_level(text)
    except (OSError, jsonc.JsoncError):
        return None

    for entry in entries:
        if entry.key != EXTRA_PATHS_KEY:
            continue
        try:
            paths = jsonc.parse_value(text[entry.value_start:entry.value_end])
        except jsonc.JsoncError:
            return None
        if not isinstance(paths, list):
            return None
        return [
            p if p.startswith(f"{LINK_NAME}/") else f"{LINK_NAME}/{p}"
            for p in paths
            if isinstance(p, str)
        ]

    return None


def render_document(settings: dict) -> str:
    """Render a complete settings.json for a project that has none yet."""
    pad = " " * INDENT
    lines = ["{"]
    for index, (key, value) in enumerate(settings.items()):
        comment = LEADING_COMMENTS.get(key)
        if comment:
            if index:
                lines.append("")
            lines.extend(f"{pad}{line}" for line in comment.split("\n"))
        lines.append(f"{pad}{json.dumps(key)}: {jsonc.render_value(value, INDENT)},")
    if len(lines) > 1:
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _union(old, new):
    """Add pow's entries to what the project already has, keeping the project's."""
    if isinstance(old, dict) and isinstance(new, dict):
        merged = dict(old)
        for key, value in new.items():
            merged.setdefault(key, value)
        return merged
    if isinstance(old, list) and isinstance(new, list):
        return old + [value for value in new if value not in old]
    return new          # the project changed the type under us: pow's value wins


def _resolve(text: str, settings: dict, seeded: frozenset) -> dict:
    """Turn the managed block into the values to write into *text*.

    :data:`MERGED_KEYS` are unioned with what the project already has, and
    *seeded* keys are dropped when the project already sets them.  Only those
    keys are read back, so an unparseable value elsewhere in the file cannot
    block init.
    """
    wanted = (MERGED_KEYS | seeded) & settings.keys()
    existing = {}
    for entry in jsonc.scan_top_level(text)[0]:
        if entry.key in wanted and entry.key not in existing:
            existing[entry.key] = jsonc.parse_value(text[entry.value_start:entry.value_end])

    resolved = {}
    for key, value in settings.items():
        if key not in existing:
            resolved[key] = value
        elif key in seeded:
            continue        # the project has spoken; leave it alone
        elif key in MERGED_KEYS:
            resolved[key] = _union(existing[key], value)
        else:
            resolved[key] = value
    return resolved


def apply(dest: Path, src_settings: Path, replace_extra_paths: bool = True) -> dict:
    """Create or merge the project's ``.vscode/settings.json``.

    Args:
        dest: the project's ``.vscode/settings.json``.
        src_settings: ``settings.json`` of the Isaac Sim install init selected,
            read only for :data:`EXTRA_PATHS_KEY`.
        replace_extra_paths: rewrite :data:`EXTRA_PATHS_KEY` with that install's
            list.  Init passes ``False`` when it did not change the project's
            Isaac Sim version, which makes the key seed-only: written when the
            project has none, otherwise left exactly as the project has it.

    Returns:
        dict with ``status`` (``Created``, ``Updated``, ``Already up to date``
        or ``Error``), ``changed`` as ``{key: (old, new)}``, and ``warning``
        when the Isaac Sim extension paths could not be read.  On ``Error`` the
        file is left exactly as it was.
    """
    paths = extra_paths(src_settings)
    settings = managed_settings(paths)
    seeded = SEEDED_KEYS if replace_extra_paths else SEEDED_KEYS | {EXTRA_PATHS_KEY}
    warning = None if paths is not None else (
        f"could not read {EXTRA_PATHS_KEY} from {src_settings}"
    )

    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_document(settings))
        return {"status": "Created", "changed": {}, "warning": warning}

    try:
        text = dest.read_text()
        patched, changed = jsonc.patch(
            text, _resolve(text, settings, seeded), remove=DEPRECATED_KEYS
        )
    except (OSError, jsonc.JsoncError) as e:
        return {"status": "Error", "changed": {}, "message": str(e), "warning": warning}

    if patched == text:
        return {"status": "Already up to date", "changed": {}, "warning": warning}

    dest.write_text(patched)
    return {"status": "Updated", "changed": changed, "warning": warning}
