"""Artifact detection rules (static/js/artifacts.js).

The rules decide what becomes a card beside the chat, and they have to hold
for output from any model: nothing here is allowed to depend on a model
following a protocol, because most of them will not. So the cases below are
written the way models actually answer - a page with no announcement, a
two-line shell snippet, a long function, a block that is still streaming.
"""

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


def _run(expression: str, payload):
    # pathToFileURL keeps the import portable: a bare Windows path is rejected
    # by Node's ESM loader ("Received protocol 'd:'").
    script = textwrap.dedent(
        r"""
        import { pathToFileURL } from 'node:url';
        import path from 'node:path';
        const mod = await import(pathToFileURL(path.resolve('static/js/artifacts.js')).href);
        const input = JSON.parse(process.argv[1]);
        console.log(JSON.stringify((%s)(mod, input)));
        """
        % expression
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(payload)],
        cwd=_REPO,
        capture_output=True,
        timeout=20,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _detect(text):
    return _run(
        "(mod, input) => mod.assignVersions(mod.detectArtifacts(input, { messageId: 'm' }))",
        text,
    )


def _fence(lang, body):
    return f"```{lang}\n{body}\n```"


def test_html_page_is_an_artifact_without_being_announced(node_available):
    """The commonest case: a model just prints a page."""
    text = "Here you go:\n\n" + _fence("html", "<!DOCTYPE html>\n<html><body><h1>Hi</h1></body></html>")
    found = _detect(text)
    assert len(found) == 1
    assert found[0]["kind"] == "html"
    assert found[0]["reason"] == "document"


def test_short_shell_and_short_code_are_left_alone(node_available):
    """A command to paste is not a deliverable, and neither is a two-liner."""
    assert _detect(_fence("bash", "pip install requests")) == []
    assert _detect(_fence("python", "print(1)\nprint(2)")) == []


def test_long_code_becomes_an_artifact(node_available):
    body = "\n".join(f"value_{i} = {i}" for i in range(20))
    found = _detect(_fence("python", body))
    assert len(found) == 1
    assert found[0]["kind"] == "code"
    assert found[0]["lang"] == "python"
    assert found[0]["reason"] == "code"


def test_declared_title_wins_over_length(node_available):
    """A model that announces its work is believed, however short it is."""
    found = _detect('```html title="Landing page"\n<div>a</div>\n```')
    assert len(found) == 1
    assert found[0]["title"] == "Landing page"
    assert found[0]["reason"] == "declared"


def test_titles_come_from_the_content_when_nobody_declared_one(node_available):
    page = _fence("html", "<!DOCTYPE html>\n<html><head><title>Invoice</title></head><body>x</body></html>")
    assert _detect(page)[0]["title"] == "Invoice"

    script = _fence("python", "\n".join(["# helper"] + [f"def solve_{i}():" for i in range(15)]))
    assert _detect(script)[0]["title"] == "solve_0"

    bare = _fence("html", "<!DOCTYPE html>\n<html><body>no title element</body></html>")
    assert _detect(bare)[0]["title"] == "HTML page"


def test_a_page_is_named_after_its_heading_when_it_has_no_title_element(node_available):
    """Models routinely ship a page with an <h1> and no <title>.

    Falling back to "HTML page" for those is not merely vague: the library
    replaces by title, so three such pages from one reply would take turns
    overwriting each other under one name.
    """
    page = _fence(
        "html",
        "<!DOCTYPE html>\n<html><body><h1>Kalkulator</h1><p>x</p></body></html>",
    )
    assert _detect(page)[0]["title"] == "Kalkulator"

    # A heading names a page, not a script: in Python a leading `# something`
    # is a remark, and it keeps being read as one.
    script = _fence("python", "\n".join(["# backup notes"] + ["x%d = %d" % (i, i) for i in range(20)]))
    assert _detect(script)[0]["title"] == "backup notes"


def test_svg_and_mermaid_are_recognised_by_shape(node_available):
    svg = _detect(_fence("svg", '<svg viewBox="0 0 10 10"><circle r="4"/></svg>'))
    assert svg[0]["kind"] == "svg"
    diagram = _detect(_fence("mermaid", "graph TD\nA-->B"))
    assert diagram[0]["kind"] == "mermaid"
    # ... and without a language on the fence, which small models often omit.
    unlabelled = _detect(_fence("", '<svg viewBox="0 0 10 10"><circle r="4"/></svg>'))
    assert unlabelled and unlabelled[0]["kind"] == "svg"


def test_a_block_still_streaming_is_marked_incomplete(node_available):
    found = _detect("wait\n\n```html\n<!DOCTYPE html>\n<html><body>partial")
    assert len(found) == 1
    assert found[0]["complete"] is False


def test_the_same_deliverable_rewritten_is_a_new_version(node_available):
    """Two pages called the same thing are v1 and v2, not two artifacts."""
    first = '```html title="Report"\n<div>one</div>\n```'
    second = '```html title="Report"\n<div>two</div>\n```'
    found = _detect(first + "\n\n" + second)
    assert [a["version"] for a in found] == [1, 2]
    assert found[0]["key"] == found[1]["key"]


def test_prose_and_inline_code_produce_nothing(node_available):
    assert _detect("Just prose, with `inline code` in it.") == []


def test_auto_open_only_in_the_live_conversation(node_available):
    """The panel opens for what was just made, not while replaying history,
    and not for an artifact the user has closed."""
    cases = [
        {"isLive": True, "isHistoryReplay": False, "dismissedKeys": [], "key": "html:report"},
        {"isLive": False, "isHistoryReplay": False, "dismissedKeys": [], "key": "html:report"},
        {"isLive": True, "isHistoryReplay": True, "dismissedKeys": [], "key": "html:report"},
        {"isLive": True, "isHistoryReplay": False, "dismissedKeys": ["html:report"], "key": "html:report"},
    ]
    got = _run("(mod, input) => input.map((c) => mod.shouldAutoOpen(c))", cases)
    assert got == [True, False, False, False]


def test_preview_document_wraps_a_fragment_and_leaves_a_page_alone(node_available):
    """An HTML artifact is served as written; a fragment gets the smallest
    page that shows it."""
    page = {"kind": "html", "code": "<!DOCTYPE html><html><body>whole</body></html>"}
    fragment = {"kind": "html", "code": "<p>fragment</p>"}
    got = _run(
        "(mod, input) => input.map((a) => mod.previewDocument(a))",
        [page, fragment],
    )
    assert got[0] == page["code"]
    assert "<p>fragment</p>" in got[1] and got[1].lstrip().startswith("<!DOCTYPE html>")
