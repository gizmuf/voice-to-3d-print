from __future__ import annotations

import pytest

from services.codegen.ast_audit import audit_script


SAFE_BUILD123D_SCRIPT = """
from build123d import *
import math

with BuildPart() as bracket:
    Box(30, 20, 4)
    with Locations((10 * math.cos(math.radians(45)), 0, 0)):
        Hole(2)

result = bracket.part
"""


@pytest.mark.parametrize(
    "dangerous_attribute",
    [
        "os",
        "sys",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "importlib",
        "builtins",
    ],
)
def test_audit_rejects_dangerous_modules_reached_through_allowed_root(
    dangerous_attribute: str,
) -> None:
    result = audit_script(
        "import build123d\n"
        f"escape = build123d.{dangerous_attribute}\n"
        "result = build123d.Box(1, 1, 1)"
    )

    assert not result.ok
    assert any(dangerous_attribute in error for error in result.errors)


@pytest.mark.parametrize(
    "dangerous_import",
    [
        "build123d.os",
        "build123d.subprocess",
        "build123d.importlib",
    ],
)
def test_audit_rejects_dangerous_dotted_imports_under_allowed_root(
    dangerous_import: str,
) -> None:
    result = audit_script(
        f"import {dangerous_import} as escape\n"
        "from build123d import Box\n"
        "result = Box(1, 1, 1)"
    )

    assert not result.ok
    assert any(dangerous_import in error for error in result.errors)


@pytest.mark.parametrize(
    "dangerous_import",
    [
        "os",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "importlib",
        "builtins",
        "fork",
        "setsid",
        "spawnv",
        "system",
        "popen",
        "Popen",
    ],
)
def test_audit_rejects_dangerous_symbols_imported_from_allowed_root(
    dangerous_import: str,
) -> None:
    result = audit_script(
        f"from build123d import {dangerous_import} as escape\n"
        "from build123d import Box\n"
        "result = Box(1, 1, 1)"
    )

    assert not result.ok
    assert any(dangerous_import in error for error in result.errors)


@pytest.mark.parametrize(
    "process_control",
    [
        "fork",
        "forkpty",
        "vfork",
        "setsid",
        "setpgid",
        "spawnl",
        "spawnv",
        "posix_spawn",
        "system",
        "popen",
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "kill",
        "killpg",
        "terminate",
    ],
)
def test_audit_rejects_process_controls_reached_through_allowed_root(
    process_control: str,
) -> None:
    result = audit_script(
        "import build123d\n"
        f"build123d.{process_control}()\n"
        "result = build123d.Box(1, 1, 1)"
    )

    assert not result.ok
    assert any(process_control in error for error in result.errors)


@pytest.mark.parametrize(
    "process_launch",
    [
        'import build123d\nbuild123d.os.system("id")',
        'import build123d\nbuild123d.sys.modules["subprocess"].run(["id"])',
        'from build123d import os as cad_os\ncad_os.system("id")',
    ],
)
def test_audit_rejects_transitive_process_launch_chains(process_launch: str) -> None:
    result = audit_script(
        f"{process_launch}\n"
        "from build123d import Box\n"
        "result = Box(1, 1, 1)"
    )

    assert not result.ok
    assert any(
        dangerous in error
        for error in result.errors
        for dangerous in ("os", "sys", "system", "run")
    )


def test_audit_allows_normal_build123d_geometry() -> None:
    result = audit_script(SAFE_BUILD123D_SCRIPT)

    assert result.ok, result.errors
