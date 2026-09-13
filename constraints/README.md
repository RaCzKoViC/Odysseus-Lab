# Foundation dependency constraints

`py311.txt` and `py314.txt` pin the resolved core dependency graph used by the
minimum supported Python CI lane and the Python 3.14 container lane. The
abstract dependency intent remains in `requirements.txt` for upstream
compatibility.

Regenerate both files with the same released `uv` version and review the diff:

```bash
uv pip compile requirements.txt --python-version 3.11 --output-file constraints/py311.txt
uv pip compile requirements.txt --python-version 3.14 --output-file constraints/py314.txt
```

Then run both CI lanes and the Docker readiness smoke test. Do not hand-edit a
resolved version without documenting why the resolver output is being
overridden.
