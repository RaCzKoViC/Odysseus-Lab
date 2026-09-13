"""Fenced code blocks render with the Odysseus-Lab header chrome and, past the
collapse threshold, inside a collapsed frame (static/js/markdown.js)."""

import re

import pytest

from test_markdown_rendering_js import _run_markdown_case, node_available  # noqa: F401


def _fence(lines, lang="python"):
    body = "\n".join(f"print({i})" for i in range(lines))
    return f"Intro\n\n```{lang}\n{body}\n```\n\nOutro"


def test_short_block_gets_header_with_language_and_tools(node_available):
    html = _run_markdown_case(_fence(3))
    assert '<pre class="code-block" data-lines="3">' in html
    assert '<span class="code-head"><span class="code-lang">python</span>' in html
    # Tools sit inside the header, copy last, regenerate before it.
    head = re.search(r'<span class="code-tools">(.*?)</span></span><code', html, re.S)
    assert head, html
    tools = head.group(1)
    assert tools.index('class="run-code"') < tools.index('class="edit-code"') < tools.index('class="regen-code"') < tools.index('class="copy-code"')
    assert 'data-code="print(0)\nprint(1)\nprint(2)"' in html
    assert "code-collapsed" not in html
    assert "code-expand" not in html


def test_long_block_starts_collapsed_with_expand_toggle(node_available):
    html = _run_markdown_case(_fence(40))
    assert '<pre class="code-block code-collapsed" data-lines="40">' in html
    assert 'class="code-expand" aria-expanded="false"' in html
    assert "Show all 40 lines" in html
    # The whole block is still in the DOM (the frame only limits height).
    code = re.search(r"<code[^>]*>(.*?)</code>", html, re.S).group(1)
    assert code.count("print(") == 40


def test_threshold_is_exclusive(node_available):
    html = _run_markdown_case(_fence(24))
    assert "code-collapsed" not in html
    html = _run_markdown_case(_fence(25))
    assert "code-collapsed" in html


def test_unlabelled_fence_reads_code(node_available):
    html = _run_markdown_case("```\nplain\n```")
    assert '<span class="code-lang">code</span>' in html
    assert '<code data-lang="">plain</code>' in html


def test_language_label_is_escaped(node_available):
    html = _run_markdown_case("```html\n<b>x</b>\n```")
    assert '<span class="code-lang">html</span>' in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
