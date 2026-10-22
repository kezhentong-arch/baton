"""Delay on the timeline (timeline.js lateOf / lateText / dueMarks): measured from the current plan (the last one set) —
after a replan nothing is late until the new date passes, then it counts from the new date. The expected texts match the
team board's tests/test_board_late.py character for character (same cases).

The timeline's arithmetic only runs in the browser, so the functions it uses are cut out of timeline.js as they are and
run with node; without node these tests are skipped."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.i18n import js_table

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "timeline.js"
NODE = shutil.which("node")
FUNCS = ("wall", "dayIso", "offsetAt", "zoneMs", "dayStartOf", "addDays", "nextDay", "dueMs", "lateText", "lateOf", "dueMarks")

# (what, plans (the one set at creation, then each change), done, abandoned, long-term, now, expected text); moments in Los Angeles
CASES = [
    ("not replanned, past it", ["2026-09-10"], None, None, False, "2026-09-12T10:00:00-07:00", "1.4 天"),
    ("replanned, new date not reached", ["2026-09-10", "2026-09-20"], None, None, False, "2026-09-12T10:00:00-07:00", ""),
    ("replanned, new date passed too", ["2026-09-10", "2026-09-20"], None, None, False, "2026-09-22T10:00:00-07:00", "1.4 天"),
    ("replanned twice, the last one counts", ["2026-09-10", "2026-09-30", "2026-09-20"], None, None, False, "2026-09-22T10:00:00-07:00", "1.4 天"),
    ("replanned, done before the new date", ["2026-09-10", "2026-09-20"], "2026-09-15T10:00:00-07:00", None, False, "2026-09-25T10:00:00-07:00", ""),
    ("replanned, done after the new date", ["2026-09-10", "2026-09-20"], "2026-09-21T10:00:00-07:00", None, False, "2026-09-25T10:00:00-07:00", "10 小时"),
    ("moved earlier counts as well", ["2026-09-10", "2026-09-08 08:00"], None, None, False, "2026-09-08T11:30:00-07:00", "4 小时"),
    ("abandoned is never late", ["2026-09-10", "2026-09-12"], None, "2026-09-20T10:00:00-07:00", False, "2026-09-25T10:00:00-07:00", ""),
    ("ongoing row with a plan is never late", ["2026-09-10"], None, None, True, "2026-09-12T10:00:00-07:00", ""),
    ("DST ends, to the hour", ["2026-11-01 10:00"], None, None, False, "2026-11-01T11:30:00-08:00", "2 小时"),
    ("DST ends, date only", ["2026-11-01"], None, None, False, "2026-11-02T10:00:00-08:00", "10 小时"),
    ("DST ends, a repeated hour takes the first", ["2026-11-01 01:30"], None, None, False, "2026-11-01T01:30:00-08:00", "1 小时"),
    ("DST starts, date only", ["2027-03-14"], None, None, False, "2027-03-15T10:00:00-07:00", "10 小时"),
    ("DST starts, to the hour", ["2027-03-14 03:30"], None, None, False, "2027-03-14T06:00:00-07:00", "3 小时"),
    ("DST starts, a skipped hour counts in winter time", ["2027-03-14 02:30"], None, None, False, "2027-03-14T05:00:00-07:00", "2 小时"),
]


def _chunk(src: str, start: int) -> str:
    """One whole definition from `start`: brackets balanced, ending at a semicolon or newline at depth 0."""
    depth, i, func = 0, start, src[start:].lstrip().startswith("function")
    while i < len(src):
        c = src[i]
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
            if depth == 0 and c == "}" and func:
                return src[start:i + 1]
        elif c in ";\n" and depth == 0 and not func:
            return src[start:i + 1]
        i += 1
    raise AssertionError("unbalanced definition in timeline.js")


def _lib(tz: str) -> str:
    src = JS.read_text(encoding="utf-8")
    parts = [f"const CFG = {{ tz: {json.dumps(tz)} }};",
             f"const I18N = {json.dumps(js_table('zh'), ensure_ascii=False)};",
             "const T = (k, v) => { const s = I18N[k]; if (s == null) return k;"
             " return v ? s.replace(/\\{(\\w+)\\}/g, (m, n) => n in v ? v[n] : m) : s; };"]
    for head in (r"const H = 3600e3", r"const fmt = ", r"const fmtIso = "):
        m = re.search(r"^[ \t]*" + head, src, re.M)
        assert m, head
        parts.append(_chunk(src, m.start()))
    for name in FUNCS:
        m = re.search(r"^[ \t]*function " + name + r"\(", src, re.M)
        assert m, f"timeline.js has no {name}"
        parts.append(_chunk(src, m.start()))
    return "\n".join(parts)


def run(body: str, tz: str = "America/Los_Angeles"):
    out = subprocess.run([NODE, "-e", _lib(tz) + "\n" + body], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _goal(dues, done=None, abandoned=None, long_term=False) -> dict:
    return {"due": dues[-1], "baseline_due": dues[0], "long_term": long_term,
            "status": "abandoned" if abandoned else ("done" if done else "active"), "done_at": done or abandoned}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_late_counts_from_current_plan_same_as_team_board():
    goals = [_goal(dues, done, abandoned, long_term) for _, dues, done, abandoned, long_term, _, _ in CASES]
    nows = [c[5] for c in CASES]
    got = run(f"""const goals = {json.dumps(goals)}, nows = {json.dumps(nows)};
process.stdout.write(JSON.stringify(goals.map((g, i) => lateText(lateOf(g, Date.parse(nows[i]))))));""")
    assert got == [c[-1] for c in CASES], [(c[0], g) for c, g in zip(CASES, got) if g != c[-1]]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_due_marks_draw_current_plan_and_grey_original():
    """The main line is the current plan, the first plan is the grey "originally" line; no red run before the new date,
    and after it the run starts at the main line. An ongoing row draws nothing; a cleared plan leaves only the grey line."""
    goals = [_goal(["2026-09-10", "2026-09-20"]), _goal(["2026-09-10", "2026-09-20"]), _goal(["2026-09-10"]),
             _goal(["2026-09-10"], long_term=True), {"due": None, "baseline_due": "2026-09-10", "long_term": False,
                                                     "status": "active", "done_at": None}]
    nows = ["2026-09-12T10:00:00-07:00", "2026-09-22T10:00:00-07:00", "2026-09-12T10:00:00-07:00",
            "2026-09-12T10:00:00-07:00", "2026-09-12T10:00:00-07:00"]
    got = run(f"""const goals = {json.dumps(goals)}, nows = {json.dumps(nows)};
process.stdout.write(JSON.stringify(goals.map((g, i) => {{ const m = dueMarks(g, Date.parse(nows[i]));
  return [m.plan && m.plan.label, m.orig && m.orig.label, m.lateLabel, m.lateFrom != null && m.lateFrom === m.plan.at]; }})));""")
    assert got == [["计划 09-20", "原计划 09-10", "", False],
                   ["计划 09-20", "原计划 09-10", "延期 1.4 天", True],
                   ["计划 09-10", None, "延期 1.4 天", True],
                   [None, None, "", False],
                   [None, "原计划 09-10", "", False]]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("tz, day, want", [
    ("America/Los_Angeles", "2027-03-14", "2027-03-14T08:00:00.000Z"),   # the day clocks go forward
    ("America/Los_Angeles", "2026-11-01", "2026-11-01T07:00:00.000Z"),   # the day clocks go back
    ("Asia/Kolkata", "2026-10-02", "2026-10-01T18:30:00.000Z"),          # a half-hour zone without daylight saving
    ("Europe/London", "2027-03-28", "2027-03-28T00:00:00.000Z"),
])
def test_midnight_is_right_on_daylight_saving_days(tz, day, want):
    assert run(f"process.stdout.write(JSON.stringify(new Date(dayStartOf({json.dumps(day)})).toISOString()));", tz) == want
