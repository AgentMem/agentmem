#!/usr/bin/env python3
"""LongDebug-Causal smoke runner, scripted dummy agent, zero LLM calls.

Repo location: evals/longdebug_causal/smoke.py
Companion to TASKS.md §8. For every task this replays two canned action
scripts against a fresh copy of the task repo:

  * trap, the naive-agent path. Proves the causal trap fires
    deterministically: the gold signature must appear at the specced
    session, persist/recur where specced, and the hidden verifier must
    end RED.
  * gold, the root-cause path. Proves the intended fix exists and the
    hidden verifier ends GREEN.

Design notes
------------
- Filler sessions are no-ops here: they validate session timing and
  workspace persistence (the workdir survives across sessions, exactly
  like the harness Docker volume), not features.
- Smoke sessions are checkpoints and may split one eval session into
  e.g. "S3-symptom" / "S3-shallow-fix".
- NORMATIVE ANCHORS: the canned edits grip onto exact strings that the
  scaffolded repos MUST contain (declared per task below, printed by
  --list, verified by preflight before anything runs). If Claude Code
  scaffolds differently, preflight fails with the precise missing
  anchor instead of a confusing mid-run error.
- Host deps: python3.11+, pytest, pytest-asyncio. CT-05 additionally
  needs network (pip installs real httpx versions); skip it with
  --offline. Docker parity is exercised by the full runner, not here.

Usage
-----
  python smoke.py                       # all tasks, both scenarios
  python smoke.py --task CT-03          # one task
  python smoke.py --scenario trap       # traps only
  python smoke.py --list                # print plans + anchors, run nothing
  python smoke.py --offline             # skip network-dependent tasks
  python smoke.py --keep --json out.json
Exit code 0 iff every selected scenario met all expectations.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Action primitives


@dataclass
class Run:
    cmd: str


@dataclass
class Sed:
    """Regex substitution. must=True -> pattern must match; count>0 -> exactly count matches."""

    path: str
    pattern: str
    repl: str
    count: int = 0  # 0 = replace all (>=1 required when must)
    must: bool = True


@dataclass
class Write:
    path: str
    content: str


@dataclass
class Append:
    path: str
    content: str


@dataclass
class Region:
    """Replace everything between start/end marker lines (markers kept)."""

    path: str
    start: str
    end: str
    new_body: str


@dataclass
class Rm:
    path: str  # file or dir, relative to workdir


Action = Run | Sed | Write | Append | Region | Rm


@dataclass
class Sess:
    name: str
    actions: list[Action] = field(default_factory=list)
    visible: str | None = None  # command run after actions
    expect_visible: bool | None = None  # True=pass, False=fail, None=don't care
    sig: str | None = None  # overrides task default signature
    expect_sig: bool | None = None  # checked on visible+hidden output
    extra_checks: list[tuple[str, bool]] = field(default_factory=list)  # (cmd, expect_pass)
    note: str = ""


@dataclass
class Task:
    tid: str
    default_sig: str
    hidden: str  # {V}=verifier dir, {W}=workdir
    anchors: list[tuple[str, str, bool]]  # (relpath, regex, must_exist)
    trap: list[Sess]
    gold: list[Sess]
    needs_network: bool = False
    final_hidden_green = {"trap": False, "gold": True}


# Execution machinery


def sh(cmd: str, cwd: Path, extra_env: dict | None = None) -> tuple[int, str]:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    try:
        p = subprocess.run(
            ["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after 600s: {cmd}\n{e.stdout or ''}\n{e.stderr or ''}"
    return p.returncode, (p.stdout + "\n" + p.stderr)


def apply(action: Action, wd: Path) -> None:
    if isinstance(action, Run):
        rc, out = sh(action.cmd, wd)
        if rc != 0:
            raise RuntimeError(f"action Run failed ({action.cmd}):\n{out[-800:]}")
    elif isinstance(action, Sed):
        f = wd / action.path
        text = f.read_text()
        # lambda repl: replacement is literal text, never a backref template.
        # re.M so ^/$ anchor per line, matching how preflight() checks anchors.
        new, n = re.subn(
            action.pattern, lambda _m: action.repl, text, count=action.count or 0, flags=re.M
        )
        if action.must and n == 0:
            raise RuntimeError(f"Sed anchor not found in {action.path}: /{action.pattern}/")
        if action.count and n != action.count:
            raise RuntimeError(f"Sed expected {action.count} matches in {action.path}, got {n}")
        f.write_text(new)
    elif isinstance(action, Write):
        f = wd / action.path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(action.content)
    elif isinstance(action, Append):
        (wd / action.path).open("a").write(action.content)
    elif isinstance(action, Region):
        f = wd / action.path
        lines = f.read_text().splitlines(keepends=True)
        try:
            i = next(k for k, line in enumerate(lines) if action.start in line)
            j = next(k for k, line in enumerate(lines) if action.end in line and k > i)
        except StopIteration as exc:
            raise RuntimeError(f"Region markers missing in {action.path}") from exc
        body = action.new_body if action.new_body.endswith("\n") else action.new_body + "\n"
        f.write_text("".join(lines[: i + 1]) + body + "".join(lines[j:]))
    elif isinstance(action, Rm):
        p = wd / action.path
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


def preflight(task: Task, repo: Path) -> list[str]:
    errs = []
    if not repo.is_dir():
        return [f"repo dir missing: {repo}"]
    for rel, pattern, must in task.anchors:
        f = repo / rel
        if not f.exists():
            if must:
                errs.append(f"missing file: {rel}")
            continue
        hit = re.search(pattern, f.read_text(), flags=re.M) is not None
        if must and not hit:
            errs.append(f"missing anchor in {rel}: /{pattern}/")
        if not must and hit:
            errs.append(f"forbidden content in {rel}: /{pattern}/ (seed drift violated)")
    return errs


def run_scenario(task: Task, scenario: str, tasks_root: Path, keep: bool) -> dict:
    repo = tasks_root / task_dir(task.tid) / "repo"
    verifier = tasks_root / task_dir(task.tid) / "verifier"
    result: dict = {"task": task.tid, "scenario": scenario, "sessions": [], "ok": True}

    errs = preflight(task, repo)
    if errs or not verifier.is_dir():
        result["ok"] = False
        result["error"] = "; ".join(errs or [f"verifier dir missing: {verifier}"])
        return result

    wd = Path(tempfile.mkdtemp(prefix=f"smoke-{task.tid}-{scenario}-"))
    shutil.copytree(repo, wd, dirs_exist_ok=True)
    hidden_cmd = task.hidden.format(V=verifier, W=wd)
    last_hidden_rc = 1
    try:
        for sess in getattr(task, scenario):
            rec = {"session": sess.name, "checks": [], "ok": True}
            try:
                for a in sess.actions:
                    apply(a, wd)
            except RuntimeError as e:
                rec.update(ok=False, error=str(e))
                result["sessions"].append(rec)
                result["ok"] = False
                break

            blob = ""
            if sess.visible:
                rc, out = sh(sess.visible, wd)
                blob += out
                if sess.expect_visible is not None:
                    good = (rc == 0) == sess.expect_visible
                    rec["checks"].append(
                        ("visible " + ("pass" if sess.expect_visible else "fail"), good)
                    )
                    rec["ok"] &= good

            last_hidden_rc, hout = sh(hidden_cmd, wd)
            blob += hout

            if sess.expect_sig is not None:
                sig = sess.sig or task.default_sig
                fired = re.search(sig, blob) is not None
                good = fired == sess.expect_sig
                rec["checks"].append(
                    (f"signature {'fires' if sess.expect_sig else 'silent'} /{sig}/", good)
                )
                rec["ok"] &= good

            for cmd, want_pass in sess.extra_checks:
                rc, out = sh(cmd, wd)
                good = (rc == 0) == want_pass
                rec["checks"].append((f"extra[{cmd}] {'pass' if want_pass else 'fail'}", good))
                rec["ok"] &= good

            result["sessions"].append(rec)
            result["ok"] &= rec["ok"]

        want_green = task.final_hidden_green[scenario]
        good = (last_hidden_rc == 0) == want_green
        result["final_hidden"] = {"expect_green": want_green, "ok": good}
        result["ok"] &= good
    finally:
        if keep:
            result["workdir"] = str(wd)
        else:
            shutil.rmtree(wd, ignore_errors=True)
    return result


def task_dir(tid: str) -> str:
    return {
        "CT-01": "CT-01_stale-artifacts",
        "CT-02": "CT-02_config-drift",
        "CT-03": "CT-03_ruled-out",
        "CT-04": "CT-04_blast-radius",
        "CT-05": "CT-05_stale-pin",
    }[tid]


# Canned plans (the dummy agent's brain), anchors are NORMATIVE for scaffold

PYT = "python -m pytest"

CT01 = Task(
    tid="CT-01",
    default_sig=r"KeyError.*display_name",
    hidden=f"{PYT} {{V}} -q",
    anchors=[
        ("app/serializer.py", r'"email": user\["email"\],', True),
        ("Makefile", r"^generate:", True),
        ("schema/user.yaml", r"- name: display_name", True),  # seed: schema HAS the field
        ("tests/fixtures/users.json", r"display_name", False),  # seed: fixtures DON'T (drift)
        ("tools/codegen.py", r"", True),
    ],
    trap=[
        Sess("S1-pagination(filler)", [], f"{PYT} tests/test_api.py -q", True, expect_sig=False),
        Sess("S2-middleware(filler)", [], f"{PYT} tests/test_api.py -q", True, expect_sig=False),
        Sess(
            "S3-strict-access",
            [
                Sed(
                    "app/serializer.py",
                    r'"email": user\["email"\],',
                    '"email": user["email"],\n        "display_name": user["display_name"],',
                    1,
                )
            ],
            f"{PYT} tests/test_api.py -q",
            False,
            expect_sig=True,
            note="ticket said 'one-liner'; stale fixtures lack the key -> KeyError",
        ),
        Sess(
            "S4-shallow-get",
            [
                Sed(
                    "app/serializer.py",
                    r'user\["display_name"\]',
                    'user.get("display_name", "")',
                    1,
                )
            ],
            f"{PYT} tests/test_api.py -q",
            True,
            sig=r"test_display_name_value",
            expect_sig=True,
            note="recurrence: crash gone, VALUES still wrong (root cause untouched)",
        ),
        Sess("S5-end", [], f"{PYT} tests/test_api.py -q", True),
    ],
    gold=[
        Sess("S1-filler", [], f"{PYT} tests/test_api.py -q", True, expect_sig=False),
        Sess("S2-filler", [], f"{PYT} tests/test_api.py -q", True, expect_sig=False),
        Sess(
            "S3-root-fix",
            [
                Run("make generate"),
                Sed(
                    "app/serializer.py",
                    r'"email": user\["email"\],',
                    '"email": user["email"],\n        "display_name": user["display_name"],',
                    1,
                ),
            ],
            f"{PYT} tests/test_api.py -q",
            True,
            expect_sig=False,
        ),
        Sess("S4-nothing-broken", [], f"{PYT} tests/test_api.py -q", True, expect_sig=False),
        Sess(
            "S5-pronouns-proactive",
            [
                Append(
                    "schema/user.yaml",
                    '  - name: pronouns\n    type: str\n    optional: true\n    default: ""\n',
                ),
                Run("make generate"),
                Sed(
                    "app/serializer.py",
                    r'"display_name": user\["display_name"\],',
                    '"display_name": user["display_name"],\n        "pronouns": user["pronouns"],',
                    1,
                ),
            ],
            f"{PYT} tests/test_api.py -q",
            True,
            expect_sig=False,
            note="schema change followed by regen -> hidden fixtures-fresh + value tests green",
        ),
    ],
)

_GOLDEN_V2 = 'GOLDEN_CITY = {"hanoi": 5, "da nang": 3, "hue": 2}'
_GOLDEN_V3 = 'GOLDEN_CITY = {"hanoi": 5, "da nang": 3, "hue": 2}\nGOLDEN_COUNTRY = {"vietnam": 10}'

CT02 = Task(
    tid="CT-02",
    default_sig=r"FAILED.*test_aggregates",
    hidden=f"{PYT} {{V}} -q",
    anchors=[
        ("config.toml", r"enabled = false", True),
        ("pipeline/normalize.py", r"def clean_city\(name: str\) -> str:\n    return name\b", True),
        (
            "pipeline/normalize.py",
            r"def clean_country\(name: str\) -> str:\n    return name\b",
            True,
        ),
        ("pipeline/cache.py", r'CACHE_SALT = "v1"', True),
        ("tests/test_pipeline.py", r"# GOLDEN-BLOCK-START", True),
        ("tests/test_pipeline.py", r"# GOLDEN-BLOCK-END", True),
    ],
    trap=[
        Sess(
            "S1-enable-cache",
            [Sed("config.toml", r"enabled = false", "enabled = true", 1)],
            f"{PYT} -q",
            True,
            expect_sig=False,
            note="cache populated with pre-casefold outputs",
        ),
        Sess(
            "S2-casefold-city",
            [
                Sed(
                    "pipeline/normalize.py",
                    r"def clean_city\(name: str\) -> str:\n    return name\b",
                    "def clean_city(name: str) -> str:\n    return name.strip().casefold()",
                ),
                Region(
                    "tests/test_pipeline.py",
                    "# GOLDEN-BLOCK-START",
                    "# GOLDEN-BLOCK-END",
                    _GOLDEN_V2,
                ),
            ],
            f"{PYT} -q -k normaliz",
            True,
            expect_sig=False,
            note="agent tests only its unit scope; stale cache now armed",
        ),
        Sess(
            "S3-symptom",
            [],
            f"{PYT} -q",
            False,
            expect_sig=True,
            note="nightly full run: cached stale normalize outputs vs new goldens",
        ),
        Sess(
            "S3-shallow-rmcache",
            [Rm(".cache")],
            f"{PYT} -q",
            True,
            expect_sig=False,
            note="rm -rf .cache 'fixes' it, keys still version-blind",
        ),
        Sess("S4-filler", [], f"{PYT} -q", True, expect_sig=False),
        Sess(
            "S5-casefold-country-RECURS",
            [
                Sed(
                    "pipeline/normalize.py",
                    r"def clean_country\(name: str\) -> str:\n    return name\b",
                    "def clean_country(name: str) -> str:\n    return name.strip().casefold()",
                ),
                Region(
                    "tests/test_pipeline.py",
                    "# GOLDEN-BLOCK-START",
                    "# GOLDEN-BLOCK-END",
                    _GOLDEN_V3,
                ),
            ],
            f"{PYT} -q",
            False,
            expect_sig=True,
            note="repeated-cause proven: same mechanism, second code change",
        ),
    ],
    gold=[
        Sess(
            "S1-enable-cache",
            [Sed("config.toml", r"enabled = false", "enabled = true", 1)],
            f"{PYT} -q",
            True,
            expect_sig=False,
        ),
        Sess(
            "S2-casefold-city",
            [
                Sed(
                    "pipeline/normalize.py",
                    r"def clean_city\(name: str\) -> str:\n    return name\b",
                    "def clean_city(name: str) -> str:\n    return name.strip().casefold()",
                ),
                Region(
                    "tests/test_pipeline.py",
                    "# GOLDEN-BLOCK-START",
                    "# GOLDEN-BLOCK-END",
                    _GOLDEN_V2,
                ),
            ],
            f"{PYT} -q -k normaliz",
            True,
            expect_sig=False,
        ),
        Sess(
            "S3-root-fix-versioned-keys",
            [
                Sed(
                    "pipeline/cache.py",
                    r'CACHE_SALT = "v1"',
                    "import hashlib as _h, pathlib as _p\n"
                    'CACHE_SALT = _h.sha1(_p.Path(__file__).with_name("normalize.py")'
                    ".read_bytes()).hexdigest()",
                    1,
                ),
                Rm(".cache"),
            ],
            f"{PYT} -q",
            True,
            expect_sig=False,
            note="key now derives from normalize.py source: future edits self-invalidate",
        ),
        Sess("S4-filler", [], f"{PYT} -q", True, expect_sig=False),
        Sess(
            "S5-casefold-country-CLEAN",
            [
                Sed(
                    "pipeline/normalize.py",
                    r"def clean_country\(name: str\) -> str:\n    return name\b",
                    "def clean_country(name: str) -> str:\n    return name.strip().casefold()",
                ),
                Region(
                    "tests/test_pipeline.py",
                    "# GOLDEN-BLOCK-START",
                    "# GOLDEN-BLOCK-END",
                    _GOLDEN_V3,
                ),
            ],
            f"{PYT} -q",
            True,
            expect_sig=False,
            note="same edit as trap-S5, passes untouched: differential demonstrated",
        ),
    ],
)

_ORDERED = f"{PYT} tests/test_single.py tests/test_batch.py -q"
_ALONE = f"{PYT} tests/test_batch.py -q"
_LOCK_FIX = (
    '_LOCKS: dict[int, "asyncio.Lock"] = {}\n\n'
    'def _lock() -> "asyncio.Lock":\n'
    "    loop = asyncio.get_running_loop()\n"
    "    if id(loop) not in _LOCKS:\n"
    "        _LOCKS[id(loop)] = asyncio.Lock()\n"
    "    return _LOCKS[id(loop)]"
)

CT03 = Task(
    tid="CT-03",
    default_sig=r"JobTimeout",
    hidden=f"{PYT} {{V}} -q",
    anchors=[
        ("worker/pool.py", r"^LOCK = asyncio\.Lock\(\)$", True),
        ("worker/pool.py", r"USE_PRIORITY_LOCK = False", True),
        ("worker/pool.py", r"async with LOCK:", True),
        ("worker/config.toml", r"timeout_s = 5", True),
        ("worker/retry.py", r"RETRIES = 3", True),
    ],
    trap=[
        Sess(
            "S0-baseline",
            [],
            _ORDERED,
            True,
            expect_sig=False,
            note="seed dormant: batch path lock-free until priority lands",
        ),
        Sess(
            "S1-arm-priority",
            [Sed("worker/pool.py", r"USE_PRIORITY_LOCK = False", "USE_PRIORITY_LOCK = True", 1)],
            f"{PYT} tests/test_single.py -q",
            True,
            expect_sig=True,
            extra_checks=[(_ALONE, True)],
            note="visible scope passes; hidden ordered run already times out; batch ALONE passes",
        ),
        Sess(
            "S2-H1-bump-timeout",
            [Sed("worker/config.toml", r"timeout_s = 5", "timeout_s = 30", 1)],
            _ORDERED,
            False,
            expect_sig=True,
            extra_checks=[(_ALONE, True)],
            note="ruled-out #1: JobTimeout survives a 6x timeout",
        ),
        Sess(
            "S4-H3-bump-retries",
            [Sed("worker/retry.py", r"RETRIES = 3", "RETRIES = 6", 1)],
            _ORDERED,
            False,
            expect_sig=True,
            note="ruled-out #2 (mock hypothesis elided in smoke); still red",
        ),
    ],
    gold=[
        Sess("S0-baseline", [], _ORDERED, True, expect_sig=False),
        Sess(
            "S1-arm-priority",
            [Sed("worker/pool.py", r"USE_PRIORITY_LOCK = False", "USE_PRIORITY_LOCK = True", 1)],
            f"{PYT} tests/test_single.py -q",
            True,
            expect_sig=True,
        ),
        Sess(
            "S2-observe-differential",
            [],
            _ORDERED,
            False,
            expect_sig=True,
            extra_checks=[(_ALONE, True)],
            note="the pivotal banked fact: order-dependent, not load-dependent",
        ),
        Sess(
            "S4-root-fix-lazy-lock",
            [
                Sed("worker/pool.py", r"^LOCK = asyncio\.Lock\(\)$", _LOCK_FIX, 1),
                Sed("worker/pool.py", r"async with LOCK:", "async with _lock():"),
            ],
            _ORDERED,
            True,
            expect_sig=False,
            note="per-loop lazy locks; timeout untouched (gold never bumped it)",
        ),
    ],
)

_UTILS_GOLD = '''"""Date parsing shared by CLI and API. Format-agnostic per REQUIREMENTS.md:
callers pass their boundary's format explicitly."""
from datetime import date, datetime

US_FMT = "%m/%d/%y"
EU_FMT = "%d/%m/%y"


def parse_date(s: str, fmt: str) -> date:
    return datetime.strptime(s.strip(), fmt).date()
'''

CT04 = Task(
    tid="CT-04",
    default_sig=r"FAILED.*(test_api_eu_values|test_no_silent_swap)",
    hidden=f"{PYT} {{V}} -q",
    anchors=[
        ("utils/dates.py", r'DATE_FMT = "%d/%m/%y"', True),
        ("cli/report.py", r"parse_date\(raw\)", True),
        ("api/filters.py", r"parse_date\(raw\)", True),
    ],
    trap=[
        Sess(
            "S0-baseline",
            [],
            f"{PYT} tests/test_api.py -q",
            True,
            expect_sig=False,
            extra_checks=[(f"{PYT} tests/test_cli.py -q", False)],
            note="ticket truth: CLI red on US dates at t0, API green",
        ),
        Sess(
            "S1-flip-shared-util",
            [Sed("utils/dates.py", r'DATE_FMT = "%d/%m/%y"', 'DATE_FMT = "%m/%d/%y"', 1)],
            f"{PYT} tests/test_cli.py -q",
            True,
            expect_sig=True,
            note="CLI green; hidden EU checks (incl. silent day<=12 swap) already red",
        ),
        Sess("S2-filler", [], f"{PYT} tests/test_cli.py -q", True, expect_sig=True),
        Sess(
            "S3-symptom",
            [],
            f"{PYT} -q",
            False,
            expect_sig=True,
            note="API surface breaks with zero lexical overlap with the S1 ticket",
        ),
        Sess("S5-end", [], None, None, expect_sig=True),
    ],
    gold=[
        Sess(
            "S0-baseline",
            [],
            f"{PYT} tests/test_api.py -q",
            True,
            expect_sig=False,
            extra_checks=[(f"{PYT} tests/test_cli.py -q", False)],
        ),
        Sess(
            "S1-root-fix-explicit-fmt",
            [
                Write("utils/dates.py", _UTILS_GOLD),
                Sed(
                    "cli/report.py",
                    r"from utils\.dates import parse_date",
                    "from utils.dates import parse_date, US_FMT",
                    1,
                ),
                Sed("cli/report.py", r"parse_date\(raw\)", "parse_date(raw, US_FMT)"),
                Sed(
                    "api/filters.py",
                    r"from utils\.dates import parse_date",
                    "from utils.dates import parse_date, EU_FMT",
                    1,
                ),
                Sed("api/filters.py", r"parse_date\(raw\)", "parse_date(raw, EU_FMT)"),
            ],
            f"{PYT} -q",
            True,
            expect_sig=False,
            note="early_root_fix path from TASKS.md: boundary formats, util agnostic",
        ),
        Sess("S3-nothing-breaks", [], f"{PYT} -q", True, expect_sig=False),
        Sess(
            "S5-parse-datetime",
            [
                Append(
                    "utils/dates.py",
                    "\n\ndef parse_datetime(s: str, fmt: str) -> datetime:\n"
                    '    date_part, _, time_part = s.strip().partition(" ")\n'
                    "    d = parse_date(date_part, fmt)\n"
                    '    h, m = time_part.split(":")\n'
                    "    return datetime(d.year, d.month, d.day, int(h), int(m))\n",
                )
            ],
            f"{PYT} -q",
            True,
            expect_sig=False,
        ),
    ],
)

_SETUP = "bash scripts/setup.sh && .venv/bin/python -m pytest -q"

CT05 = Task(
    tid="CT-05",
    default_sig=r"unexpected keyword argument 'proxies'",
    hidden="bash {V}/clean_runner.sh {W}",
    anchors=[
        ("requirements.txt", r"^httpx$", True),
        ("constraints.txt", r"httpx==0\.25", True),
        ("svc/client.py", r"proxies=", True),
        ("scripts/setup.sh", r"-c constraints", False),  # local setup must NOT use -c
    ],
    needs_network=True,
    trap=[
        Sess(
            "S1-symptom",
            [],
            _SETUP,
            False,
            expect_sig=True,
            note="fresh clone pulls latest httpx; code still passes proxies=",
        ),
        Sess(
            "S1-pin",
            [Sed("requirements.txt", r"^httpx$", "httpx==0.25.*", 1), Rm(".venv")],
            _SETUP,
            True,
            expect_sig=False,
        ),
        Sess("S2-filler", [], None, None),
        Sess(
            "S4-upgrade-misses-second-pin",
            [
                Sed("requirements.txt", r"^httpx==0\.25\.\*$", "httpx>=0.28", 1),
                Sed("svc/client.py", r"proxies=", "proxy="),
                Rm(".venv"),
            ],
            _SETUP,
            True,
            sig=r"ResolutionImpossible|Cannot install|conflict",
            expect_sig=True,
            note="local green (no -c); hidden clean-runner (with -c) hits the buried pin",
        ),
        Sess(
            "S5-harmful-repin",
            [Sed("requirements.txt", r"^httpx>=0\.28$", "httpx==0.25.*", 1), Rm(".venv")],
            _SETUP,
            False,
            sig=r"unexpected keyword argument 'proxy'",
            expect_sig=True,
            note="'the bank said stay on 0.25', stale memory replayed makes it worse",
        ),
    ],
    gold=[
        Sess("S1-symptom", [], _SETUP, False, expect_sig=True),
        Sess(
            "S1-pin",
            [Sed("requirements.txt", r"^httpx$", "httpx==0.25.*", 1), Rm(".venv")],
            _SETUP,
            True,
            expect_sig=False,
        ),
        Sess("S2-filler", [], None, None),
        Sess(
            "S4-upgrade-ALL-pin-sites",
            [
                Sed("requirements.txt", r"^httpx==0\.25\.\*$", "httpx>=0.28", 1),
                Sed("svc/client.py", r"proxies=", "proxy="),
                Sed("constraints.txt", r"^httpx==0\.25[^\n]*\n?", "", 1),
                Rm(".venv"),
            ],
            _SETUP,
            True,
            sig=r"ResolutionImpossible|Cannot install|conflict",
            expect_sig=False,
            note="supersession done right: requirements + constraints + code together",
        ),
        Sess("S5-clean-runner-green", [], _SETUP, True, expect_sig=False),
    ],
)

TASKS = {t.tid: t for t in (CT01, CT02, CT03, CT04, CT05)}

# CLI / reporting


def show_plans(tasks: list[Task]) -> None:
    for t in tasks:
        print(f"\n=== {t.tid} ===  default_sig=/{t.default_sig}/  hidden: {t.hidden}")
        print("  normative anchors:")
        for rel, pat, must in t.anchors:
            print(f"    [{'must' if must else 'must-NOT'}] {rel}: /{pat}/")
        for scen in ("trap", "gold"):
            print(f"  {scen}:")
            for s in getattr(t, scen):
                bits = [f"{len(s.actions)} action(s)"]
                if s.visible:
                    bits.append(f"visible={'pass' if s.expect_visible else 'fail'}")
                if s.expect_sig is not None:
                    bits.append(f"sig={'fires' if s.expect_sig else 'silent'}")
                note = f"  # {s.note}" if s.note else ""
                print(f"    {s.name:34s} {', '.join(bits)}{note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task", choices=sorted(TASKS), action="append")
    ap.add_argument("--scenario", choices=["trap", "gold"], action="append")
    ap.add_argument("--tasks-root", default=Path(__file__).resolve().parent, type=Path)
    ap.add_argument("--offline", action="store_true", help="skip network-dependent tasks (CT-05)")
    ap.add_argument("--keep", action="store_true", help="keep workdirs for inspection")
    ap.add_argument("--list", action="store_true", help="print plans + anchors, run nothing")
    ap.add_argument("--json", type=Path, help="write full results as JSON")
    args = ap.parse_args()

    tasks = [TASKS[k] for k in (args.task or sorted(TASKS))]
    scenarios = args.scenario or ["trap", "gold"]

    if args.list:
        show_plans(tasks)
        return 0

    results, failed = [], 0
    for t in tasks:
        if t.needs_network and args.offline:
            print(f"{t.tid}: SKIP (needs network, --offline)")
            results.append({"task": t.tid, "skipped": True})
            continue
        for scen in scenarios:
            r = run_scenario(t, scen, args.tasks_root, args.keep)
            results.append(r)
            mark = "OK " if r["ok"] else "FAIL"
            print(
                f"\n[{mark}] {t.tid} / {scen}"
                + (f"  ({r.get('error', '')})" if "error" in r else "")
            )
            for s in r.get("sessions", []):
                sm = "ok " if s["ok"] else "FAIL"
                print(f"    {sm} {s['session']}")
                for name, good in s["checks"]:
                    print(f"         {'✓' if good else '✗'} {name}")
                if "error" in s:
                    print(f"         ! {s['error']}")
            if "final_hidden" in r:
                fh = r["final_hidden"]
                print(
                    f"    {'ok ' if fh['ok'] else 'FAIL'} final hidden verifier "
                    f"{'GREEN' if fh['expect_green'] else 'RED'} as expected"
                )
            failed += 0 if r["ok"] else 1
            if r.get("workdir"):
                print(f"    workdir kept: {r['workdir']}")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
    print(
        f"\n{'ALL GREEN' if failed == 0 else f'{failed} scenario(s) FAILED'} "
        f", traps are {'deterministic; safe to spend model tokens' if failed == 0 else 'NOT validated'}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
