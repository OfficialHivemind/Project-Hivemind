"""The dependency rule, enforced rather than documented.

From the design: `vision` never imports `platform`; `nav` never imports `tasks`;
only `platform` imports Wayland. These are not stylistic preferences -- they are
what keeps most of the codebase testable with no game, no compositor and no GPU.
The moment `vision` imports `platform`, every vision test needs a Wayland socket,
and the offline test suite that makes this project tractable stops working.

This was promised in the plan as an "import-linter test" and did not exist. It
does now, using the stdlib ast module rather than a new dependency.

There is a second rule with a different reason. The GUI must not import
`platform` because the two run as SEPARATE PROCESSES: the bot lives inside the
nested compositor it drives, and the GUI lives in the KDE session where you can
see it. A GUI that imported the Wayland layer would fail to start on a machine
where the bot is not running, which is exactly when you most want to look at it.
"""
import ast
import os
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src/hivemind"

# package -> packages it may NOT import
FORBIDDEN = {
    "vision": {"platform", "act", "tasks", "brain", "gui"},
    "nav": {"tasks", "brain", "gui", "platform"},
    "world": {"platform", "gui", "act", "tasks"},
    "economy": {"platform", "gui", "act"},
    "telemetry": {"platform", "gui", "vision", "nav"},
    "ipc": {"platform", "gui", "vision", "nav"},
    "gui": {"platform"},
}

WAYLAND = {"pywayland", "wayland"}


def modules_of(package: str):
    directory = SRC / package
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def imported_packages(path: pathlib.Path) -> set[str]:
    """Which hivemind subpackages this module imports, absolute or relative."""
    tree = ast.parse(path.read_text())
    own = path.relative_to(SRC).parts[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # relative: level 1 is this package, 2 is hivemind, and so on
                if node.level >= 2 and node.module:
                    found.add(node.module.split(".")[0])
            elif node.module and node.module.startswith("hivemind."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("hivemind."):
                    found.add(alias.name.split(".")[1])
    return found - {own}


def raw_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_package_respects_its_dependency_rule(package):
    banned = FORBIDDEN[package]
    offences = []
    for path in modules_of(package):
        bad = imported_packages(path) & banned
        if bad:
            offences.append(f"{path.relative_to(SRC)} imports {sorted(bad)}")
    assert not offences, "\n".join(offences)


def test_only_platform_touches_wayland():
    offences = []
    for package in ("vision", "nav", "world", "economy", "tasks", "telemetry",
                    "ipc", "gui", "act", "brain", "behave"):
        for path in modules_of(package):
            bad = raw_imports(path) & WAYLAND
            if bad:
                offences.append(f"{path.relative_to(SRC)} imports {sorted(bad)}")
    assert not offences, "\n".join(offences)


def test_the_gui_never_imports_the_wayland_layer():
    """The GUI must start on a machine where the bot is not running."""
    for path in modules_of("gui"):
        assert "platform" not in imported_packages(path), path


@pytest.mark.parametrize("package", ["vision", "nav", "world", "economy",
                                     "tasks", "telemetry", "ipc"])
def test_core_packages_import_without_qt_or_wayland(package):
    """Importing them must not drag in PySide6 or a compositor connection.

    Run in a SUBPROCESS on purpose. The first version asserted on this
    interpreter's `sys.modules`, which by then contained pywayland because an
    unrelated test had imported the platform layer -- so it was measuring the
    test session's history rather than the package's dependencies. A clean
    interpreter is the only place this question has a meaningful answer.
    """
    import subprocess
    import sys
    names = ["hivemind." + ".".join(p.relative_to(SRC).with_suffix("").parts)
             for p in modules_of(package)]
    if not names:
        pytest.skip(f"{package} has no modules yet")
    script = (
        "import sys, importlib\n"
        f"for n in {names!r}: importlib.import_module(n)\n"
        "leaked = [m for m in ('pywayland', 'PySide6') if m in sys.modules]\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True,
                            cwd=str(SRC.parents[1]),
                            env={**os.environ, "PYTHONPATH": str(SRC.parent)})
    assert result.returncode == 0, result.stderr
    leaked = result.stdout.strip()
    assert not leaked, f"{package} pulls in {leaked}"


# --- data files must be found from the package, not the working directory ---

def test_no_module_hardcodes_a_cwd_relative_data_path():
    """`Path("data/...")` is relative to wherever the process was started.

    Six modules spelled their defaults that way. Running the identical suite
    from /tmp gave 9 failures and 19 skips instead of 417 passes, and the GUI
    launched from the home directory showed an empty Fields tab -- silently,
    because load_layout swallows the OSError and then drops every FieldStatus
    event for an unknown field. Wrong answers are worse than errors, so this
    is guarded rather than remembered.
    """
    offenders = []
    for path in SRC.rglob("*.py"):
        if "/gen/" in str(path):            # generated Wayland bindings
            continue
        if path.name == "datapaths.py":     # it documents the pattern it bans
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for prefix in ('Path("data/', "Path('data/",
                           'Path("var/', "Path('var/",
                           'Path("src/', "Path('src/"):
                if prefix in stripped:
                    offenders.append(f"{path.relative_to(SRC)}:{number}: {stripped}")
    assert not offenders, (
        "use hivemind.datapaths.data()/var() instead of a cwd-relative path:\n"
        + "\n".join(offenders))


def test_the_data_root_resolves_to_real_files():
    from hivemind.datapaths import DATA_ROOT, data
    assert DATA_ROOT.is_absolute()
    assert data("world", "fields.yaml").exists()
    assert data("world", "paths.yaml").exists()


# ---------------------------------------------------------------------------
# Disabled safety checks
# ---------------------------------------------------------------------------
def test_no_safety_check_is_disabled_with_a_constant_condition():
    """`if False:` must never survive in shipped code.

    MEASURED, and this is why the test exists: `brain/farm.py` carried

        if False:
            report.stopped_because = (
                f"{report.barren_streak} cycles in a row measured nothing ...")
            break

    for an unknown length of time. Everything around it was live -- the
    constant MAX_BARREN_CYCLES, the constructor argument, the
    `Report.barren_streak` property -- so the guard read as working at every
    point except the one that decides. It was almost certainly turned off to
    stop a diagnostic run ending early, and then never turned back on.

    What it cost: the farm loop's only defence against "I am going through the
    motions and collecting nothing" was gone, so a night of barren cycles ran
    to morning instead of stopping after three. That is exactly what was
    observed -- the bot sat at the red cannon farming nothing for hours, and a
    person watching had to be the one to notice.

    A constant condition is invisible in review precisely because it is one
    token. A test is the right place to catch it.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "src"
    offences: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "/gen/" in str(path):          # generated Wayland bindings
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.While)):
                continue
            test = node.test
            # `if False:` / `if 0:` / `if True:` -- a literal decides it
            if isinstance(test, ast.Constant) and isinstance(
                    test.value, (bool, int)):
                # `while True:` is a legitimate loop idiom; `if True:` is not.
                if isinstance(node, ast.While) and test.value is True:
                    continue
                offences.append(
                    f"{path.relative_to(root)}:{node.lineno} "
                    f"{type(node).__name__.lower()} {test.value!r}")
            # `... and False` / `... or True` -- a short-circuit decides it
            elif isinstance(test, ast.BoolOp):
                for value in test.values:
                    if isinstance(value, ast.Constant) and isinstance(
                            value.value, bool):
                        offences.append(
                            f"{path.relative_to(root)}:{node.lineno} "
                            f"condition short-circuited by {value.value!r}")

    assert not offences, (
        "a condition in shipped code is decided by a constant, which disables "
        "whatever it guards while leaving it looking live:\n  "
        + "\n  ".join(offences))


def test_the_stale_cleanup_only_ever_targets_our_own_compositor():
    """It must be impossible for this to kill the owner's own game.

    The owner plays Bee Swarm himself. A cleanup that matched on "sober",
    "roblox" or "hyprland" could end his session, so the match is on the
    config path this class writes and nothing else uses, and the thing killed
    is the COMPOSITOR rather than the game -- a Sober on the host display is
    not a client of it and cannot be caught even in principle.
    """
    import ast
    import inspect
    from hivemind.platform.session import Session

    source = inspect.getsource(Session.clear_stale)
    assert "self.config_path" in source, (
        "the cleanup must identify our compositor by our own config path")

    # Check the CODE, not the prose. The docstring explains why Sober is not
    # targeted, so a naive substring search over the whole source matches its
    # own explanation.
    import textwrap
    tree = ast.parse(textwrap.dedent(source))
    function = tree.body[0]
    # The docstring EXPLAINS why Sober is not targeted, so it must be excluded
    # by identity -- comparing text fails because ast.get_docstring returns a
    # cleaned copy while the node holds the raw one.
    docstring_node = None
    if (function.body and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)):
        docstring_node = function.body[0].value
    literals = [node.value.lower() for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node is not docstring_node]
    for dangerous in ("sober", "roblox", "vinegar"):
        offenders = [text for text in literals if dangerous in text]
        assert not offenders, (
            f"the cleanup matches on {offenders!r}, which can catch the "
            f"owner's own game — it must match only our config path")
    assert "pkill" not in literals and "killall" not in literals
