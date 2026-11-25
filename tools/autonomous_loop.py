#!/usr/bin/env python3
"""autonomous_loop.py — fully autonomous sfile test loop driver.

Runs the test loop WITHOUT agent intervention, round after round, until
a stop condition is met. No agent has to reason through each round.

Each round:
  1. Regenerate the format table (make table) and rebuild (make).
  2. Run the test suite (tests/run_tests.py) and read the counts from
     tests/results.json: PASS / PARTIAL / FAIL / NO SAMPLE.
  3. Write LOOP_STATUS (JSON) and log the counts.
  4. If NO SAMPLE > 0 AND the sample collectors look quiescent (no new
     sample file in 15 min) AND fewer than 2 fetch passes have run:
     retry-fetch the still-missing samples with tools/bulk_fetch.py
     (page URLs only, filtered manifest), then re-run the tests.
  5. Commit any changes (counts in the message).
  6. Check the stop conditions; sleep 10 min between rounds.

Stop conditions (whichever comes first):
  - NO SAMPLE stops decreasing for 2 consecutive rounds, OR
  - PASS plateaus (does not increase) for 2 consecutive rounds, OR
  - 15 rounds done.
After stopping: final commit, then a PLAIN `git push github main`
(no --force — the remote has unrelated history, so a plain push is
expected to be rejected; that failure is logged, not forced, and the
reconcile decision stays with the user).

This driver does NOT invent new overrides — it only re-runs the
mechanical loop (regenerate, rebuild, test, fetch-retry, commit).
New FAILs are recorded in tests/results.json and LOOP_STATUS for a
human/agent to fix later; the PASS plateau stop condition is what
ends the loop when the mechanical fixes are exhausted.

Usage:
    python3 tools/autonomous_loop.py
Env overrides (for testing):
    LOOP_START_ROUND (default 11), LOOP_MAX_ROUNDS (default 15),
    LOOP_SLEEP_SECS (default 600), LOOP_MAX_FETCH (default 2),
    LOOP_QUIET_SECS (default 900).
Resumes: if LOOP_STATUS already exists with a round number, the
driver starts at round+1 (so a test run of one round does not
duplicate it).
Logs go to stdout (launch with nohup ... > loop.log 2>&1 &).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "tests", "results.json")
STATUS_PATH = os.path.join(ROOT, "LOOP_STATUS")
START_ROUND = int(os.environ.get("LOOP_START_ROUND", "11"))
MAX_ROUNDS = int(os.environ.get("LOOP_MAX_ROUNDS", "15"))
SLEEP_SECS = int(os.environ.get("LOOP_SLEEP_SECS", "600"))
MAX_FETCH = int(os.environ.get("LOOP_MAX_FETCH", "2"))
QUIET_SECS = int(os.environ.get("LOOP_QUIET_SECS", "900"))
SAMPLES = os.path.join(ROOT, "samples")
MANIFEST = os.path.join(ROOT, "tools", "sample_urls.json")


def log(msg):
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd, cwd=ROOT, timeout=None):
    """Run a command, return (returncode, stdout+stderr). Never raises."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {(e.stdout or b'').decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001 - driver must not crash
        return 1, f"EXCEPTION: {e}"


def read_counts():
    """Read PASS/PARTIAL/FAIL/NO SAMPLE from tests/results.json."""
    try:
        with open(RESULTS) as f:
            res = json.load(f)
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: cannot read {RESULTS}: {e}")
        return None
    c = {"pass": 0, "partial": 0, "fail": 0, "no_sample": 0}
    for rec in res.values():
        r = rec.get("result")
        if r == "pass":
            c["pass"] += 1
        elif r == "partial":
            c["partial"] += 1
        elif r == "fail":
            c["fail"] += 1
        elif r == "no-sample":
            c["no_sample"] += 1
    c["failing"] = sorted(t for t, rec in res.items() if rec.get("result") == "fail")
    return c


def write_status(round_no, counts, status, stop_reason=None, push_result=None,
                 nosample_stall=0, pass_stall=0):
    st = {
        "round": round_no,
        "pass": counts["pass"] if counts else None,
        "partial": counts["partial"] if counts else None,
        "fail": counts["fail"] if counts else None,
        "no_sample": counts["no_sample"] if counts else None,
        "failing_tasks": counts.get("failing", []) if counts else [],
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": status,
        "stop_reason": stop_reason,
        "push_result": push_result,
        "nosample_stall": nosample_stall,
        "pass_stall": pass_stall,
    }
    with open(STATUS_PATH, "w") as f:
        json.dump(st, f, indent=2)
    return st


def newest_sample_mtime():
    """Newest mtime among samples/task-* files, or None if there are none."""
    newest = None
    try:
        for name in os.listdir(SAMPLES):
            if name.startswith("task-"):
                try:
                    m = os.path.getmtime(os.path.join(SAMPLES, name))
                except OSError:
                    continue
                if newest is None or m > newest:
                    newest = m
    except OSError:
        pass
    return newest


def collectors_quiescent():
    newest = newest_sample_mtime()
    if newest is None:
        return True
    return (time.time() - newest) > QUIET_SECS


def fetch_missing(counts):
    """Retry-fetch the still-missing samples (page URLs only).

    Builds a filtered manifest of just the NO SAMPLE tasks and runs
    tools/bulk_fetch.py on it. Returns True if the fetch ran.
    """
    try:
        with open(RESULTS) as f:
            res = json.load(f)
    except Exception as e:  # noqa: BLE001
        log(f"fetch: cannot read results: {e}")
        return False
    missing = sorted((int(t) for t, rec in res.items()
                      if rec.get("result") == "no-sample"))
    if not missing:
        return False
    try:
        with open(MANIFEST) as f:
            manifest = json.load(f)
    except Exception as e:  # noqa: BLE001
        log(f"fetch: cannot read manifest: {e}")
        return False
    sub = {str(t): manifest[str(t)] for t in missing if str(t) in manifest}
    if not sub:
        log(f"fetch: {len(missing)} missing but none in manifest; skipping")
        return False
    tmp = f"/tmp/sfile_fetch_manifest_{os.getpid()}.json"
    with open(tmp, "w") as f:
        json.dump(sub, f)
    log(f"fetch: retrying {len(sub)} missing tasks via bulk_fetch.py")
    rc, out = run(["python3", "tools/bulk_fetch.py", tmp, "samples", "8"],
                  timeout=3600)
    try:
        os.remove(tmp)
    except OSError:
        pass
    # bulk_fetch prints a summary line; keep the tail of it.
    tail = "\n".join(out.strip().splitlines()[-6:]) if out.strip() else "(no output)"
    log(f"fetch: bulk_fetch rc={rc}\n{tail}")
    return True


def commit_if_changes(round_no, counts):
    rc, out = run(["git", "status", "--porcelain"])
    if rc != 0:
        log(f"commit: git status failed: {out.strip()}")
        return False
    if not out.strip():
        log("commit: nothing to commit")
        return False
    rc, out = run(["git", "add", "-A"])
    if rc != 0:
        log(f"commit: git add failed: {out.strip()}")
        return False
    msg = (f"Autonomous loop round {round_no}: PASS {counts['pass']}, "
           f"PARTIAL {counts['partial']}, FAIL {counts['fail']}, "
           f"NO SAMPLE {counts['no_sample']}")
    rc, out = run(["git", "commit", "-m", msg])
    if rc != 0:
        log(f"commit: git commit failed: {out.strip()}")
        return False
    log(f"commit: {msg}")
    return True


def final_push():
    """Plain push of main to the github remote (never --force).

    The remote has unrelated history, so this is expected to be
    rejected (non-fast-forward). That is logged, not forced.
    """
    rc, out = run(["git", "remote", "get-url", "github"])
    if rc != 0:
        return "skipped: no github remote configured"
    rc, out = run(["git", "push", "github", "main"], timeout=300)
    tail = "\n".join(out.strip().splitlines()[-4:]) if out.strip() else "(no output)"
    if rc == 0:
        return "ok: pushed main to github"
    return f"FAILED (rc={rc}): {tail} -- reconcile decision still needed (do NOT force-push)"


def main():
    # Resume: start after the round recorded in LOOP_STATUS, if present.
    start = START_ROUND
    try:
        with open(STATUS_PATH) as f:
            prev_status = json.load(f)
        if isinstance(prev_status.get("round"), int):
            start = max(start, prev_status["round"] + 1)
            log(f"resuming after round {prev_status['round']}; starting at {start}")
    except (OSError, ValueError):
        pass
    log(f"autonomous loop starting at round {start} "
        f"(max {MAX_ROUNDS} rounds, sleep {SLEEP_SECS}s, "
        f"max fetch passes {MAX_FETCH}, quiet {QUIET_SECS}s)")
    prev_nosample = None
    prev_pass = None
    nosample_stall = 0
    pass_stall = 0
    fetch_passes = 0
    counts = None
    stop_reason = None
    round_no = start
    rounds_done = 0

    while rounds_done < MAX_ROUNDS:
        rounds_done += 1
        log(f"=== round {round_no} ===")
        # 1. Regenerate table + rebuild (picks up overrides; cheap no-op
        #    when nothing changed).
        rc, out = run(["make", "table"])
        if rc != 0:
            log(f"round {round_no}: make table FAILED:\n{out.strip()[-800:]}")
        rc, out = run(["make"])
        if rc != 0:
            log(f"round {round_no}: make FAILED:\n{out.strip()[-800:]}")
        # 2. Run the test suite.
        rc, out = run(["python3", "tests/run_tests.py", "./sfile", "samples"],
                      timeout=600)
        if rc != 0:
            log(f"round {round_no}: run_tests.py FAILED rc={rc}:\n{out.strip()[-800:]}")
        counts = read_counts()
        if counts is None:
            log(f"round {round_no}: no counts available; treating as stalled")
            counts = {"pass": prev_pass if prev_pass is not None else 0,
                      "partial": 0, "fail": 0,
                      "no_sample": prev_nosample if prev_nosample is not None else 0,
                      "failing": []}
        log(f"round {round_no}: PASS {counts['pass']}, PARTIAL {counts['partial']}, "
            f"FAIL {counts['fail']}, NO SAMPLE {counts['no_sample']} "
            f"(failing: {counts.get('failing', [])})")
        # 3. Fetch retry (only when quiescent, and only a few times).
        if counts["no_sample"] > 0 and fetch_passes < MAX_FETCH:
            if collectors_quiescent():
                log(f"round {round_no}: collectors quiescent; running fetch pass "
                    f"#{fetch_passes + 1}")
                if fetch_missing(counts):
                    fetch_passes += 1
                    rc, out = run(["python3", "tests/run_tests.py", "./sfile", "samples"],
                                  timeout=600)
                    new_counts = read_counts()
                    if new_counts is not None:
                        counts = new_counts
                        log(f"round {round_no} after fetch: PASS {counts['pass']}, "
                            f"PARTIAL {counts['partial']}, FAIL {counts['fail']}, "
                            f"NO SAMPLE {counts['no_sample']}")
            else:
                log(f"round {round_no}: collectors still active (new sample < "
                    f"{QUIET_SECS}s ago); skipping fetch pass")
        # 4. Status + commit.
        write_status(round_no, counts, "running",
                     nosample_stall=nosample_stall, pass_stall=pass_stall)
        commit_if_changes(round_no, counts)
        # 5. Stop conditions.
        if prev_nosample is not None:
            if counts["no_sample"] >= prev_nosample:
                nosample_stall += 1
            else:
                nosample_stall = 0
            if counts["pass"] <= prev_pass:
                pass_stall += 1
            else:
                pass_stall = 0
        prev_nosample = counts["no_sample"]
        prev_pass = counts["pass"]
        log(f"round {round_no}: stalls: no-sample={nosample_stall}, pass={pass_stall}")
        if nosample_stall >= 2:
            stop_reason = "NO SAMPLE stopped decreasing for 2 consecutive rounds"
            break
        if pass_stall >= 2:
            stop_reason = "PASS plateaued for 2 consecutive rounds"
            break
        if rounds_done >= MAX_ROUNDS:
            stop_reason = f"reached max rounds ({MAX_ROUNDS})"
            break
        round_no += 1
        log(f"sleeping {SLEEP_SECS}s before round {round_no}")
        time.sleep(SLEEP_SECS)

    if stop_reason is None:
        stop_reason = f"reached max rounds ({MAX_ROUNDS})"
    log(f"loop stopping: {stop_reason}")
    # Final commit (if the last round left uncommitted changes).
    if counts is not None:
        commit_if_changes(round_no, counts)
    push_result = final_push()
    log(f"final push: {push_result}")
    write_status(round_no, counts, "done", stop_reason=stop_reason,
                 push_result=push_result,
                 nosample_stall=nosample_stall, pass_stall=pass_stall)
    log(f"DONE. Final: round {round_no}, PASS {counts['pass'] if counts else '?'}, "
        f"NO SAMPLE {counts['no_sample'] if counts else '?'}; {stop_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
