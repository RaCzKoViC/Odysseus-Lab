"""Decision logic of the floating jump arrows (static/js/scrollJump.js)."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _compute(cases):
    # pathToFileURL keeps the import portable: a bare Windows path is rejected
    # by Node's ESM loader ("Received protocol 'd:'").
    script = textwrap.dedent(
        r"""
        import { pathToFileURL } from 'node:url';
        import path from 'node:path';
        const mod = await import(pathToFileURL(path.resolve('static/js/scrollJump.js')).href);
        const cases = JSON.parse(process.argv[1]);
        console.log(JSON.stringify(cases.map((c) => mod.computeJumpState(c))));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(cases)],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}")
    return json.loads(result.stdout.splitlines()[-1])


def test_long_reply_shows_down_arrow_while_its_end_is_below_the_fold(node_available):
    base = {"scrollTop": 400, "clientHeight": 600, "msgTop": 100, "msgBottom": 2400}
    down, up, idle = _compute([
        {**base, "direction": "down"},
        {**base, "direction": "up"},
        {**base, "direction": None},
    ])
    assert down == "down"
    assert up == "up"  # message starts above the viewport, so scrolling up offers its start
    assert idle == "none"


def test_short_messages_never_show_arrows(node_available):
    base = {"scrollTop": 400, "clientHeight": 600, "msgTop": 300, "msgBottom": 700}
    assert _compute([{**base, "direction": "down"}, {**base, "direction": "up"}]) == ["none", "none"]


def test_arrows_hide_once_the_edge_is_reached(node_available):
    # End of the message already inside the viewport: no down arrow.
    at_end = {"direction": "down", "scrollTop": 1800, "clientHeight": 600, "msgTop": 100, "msgBottom": 2400}
    # Start of the message already visible: no up arrow.
    at_start = {"direction": "up", "scrollTop": 90, "clientHeight": 600, "msgTop": 100, "msgBottom": 2400}
    assert _compute([at_end, at_start]) == ["none", "none"]


def test_module_does_not_touch_the_dom_when_loaded_headless(node_available):
    # Importing under Node (no document) must not throw: the auto-init is guarded.
    assert _compute([{"direction": "down", "scrollTop": 0, "clientHeight": 0, "msgTop": 0, "msgBottom": 10}]) == ["none"]
