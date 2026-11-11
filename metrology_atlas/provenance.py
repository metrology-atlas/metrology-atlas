# SPDX-License-Identifier: MIT
"""Run records: how each saved output was made, so an atlas can trace a number back to its data.

A run record is a small JSON file written beside a tool's outputs, in OUT/_runs/, one per invocation (a resumed run
adds a file; nothing is overwritten). It holds the command, the script and the git state of its repository, the
git state of the local packages on PYTHONPATH, every input file or folder named on the command line with its
SHA-256 (or a cheap fingerprint when it is large), and, at the end, the output files with their SHA-256 and the exit
code. The atlas's provenance graph joins these records with the parameters' sources.

Standard library only, so analysis environments can run it as a file without installing the atlas:

    python provenance.py record --out DIR -- python tools/x.py agg part*.jsonl --out DIR
        run the command and record it (the exit code is passed on)
    python provenance.py begin --out DIR --script tools/x.py -- ARGS...       prints the record's path
    python provenance.py end RECORD --exit-code N
        for a driver script (run_tool_scan.sh) that starts the parts itself
    python provenance.py reconstructed --out DIR --script tools/x.py --note TEXT [--output FILE ...] -- ARGS...
        a record written afterwards from notes (runbooks, the work plan, git), marked as such
    python provenance.py show DIR                                              the records of a folder

Paths are stored against named roots so that one record reads the same on every machine that mounts the folders
differently: METROLOGY_ATLAS_ROOTS="W=/mnt/c/vitalDB/work;code=/mnt/c/code;R=/mnt/c/vitalDB/release" gives
"W:primus_sync_accuracy_v4/part_0.jsonl". Paths under no root are stored as they are. Without the variable, the roots
come from the roots file, ~/.config/metrology-atlas/roots (or METROLOGY_ATLAS_ROOTS_FILE): one NAME=PATH per line,
'#' for comments, a relative PATH taken from the file's folder. A name may appear more than once: the first entry that
exists on this machine is where the root is; the others are aliases, so that records written elsewhere (or before
the roots were set, with absolute paths) map back to the same names. The variable's entries come before the file's.
A root itself given as an input (--work $W) is recorded as {"kind": "root"} without reading it: name the files read
under it with --input.

Inputs are the command's arguments that name an existing file or folder (also the value of --opt=PATH), apart from
the output folder and anything inside it, plus any --input PATH given to the recorder for files the command reads
without naming them (a fixed path under a work folder). A file up to --hash-limit bytes (default 200 MB) gets its SHA-256; a
larger one its size and modification time. A folder gets a tree hash (SHA-256 over each file's relative path and
SHA-256) when it has at most --tree-limit files (default 2,000) and every file is under the hash limit; otherwise a
fingerprint (file count, total size, newest modification time).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

SCHEMA = "metrology-atlas-run/0.2"
HASH_LIMIT = 200 * 2**20
TREE_LIMIT = 2000
RUNS = "_runs"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


ROOTS_FILE = Path.home() / ".config" / "metrology-atlas" / "roots"


class Roots:
    """Named roots and their aliases: from METROLOGY_ATLAS_ROOTS, then the roots file."""

    def __init__(self, entries: list[tuple[str, Path]]):
        self.entries = entries                                   # in order: the first existing one is local
        self.longest = sorted(entries, key=lambda x: -len(str(x[1])))

    @classmethod
    def load(cls) -> "Roots":
        entries: list[tuple[str, Path]] = []
        for part in os.environ.get("METROLOGY_ATLAS_ROOTS", "").split(";"):
            if "=" in part:
                name, path = part.split("=", 1)
                if name.strip() and path.strip():
                    entries.append((name.strip(), Path(os.path.abspath(path.strip()))))
        f = Path(os.environ.get("METROLOGY_ATLAS_ROOTS_FILE") or ROOTS_FILE)
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                name, path = (x.strip() for x in line.split("=", 1))
                if name and path:
                    q = Path(path).expanduser()
                    entries.append((name, Path(os.path.abspath(q if q.is_absolute() else f.parent / q))))
        return cls(entries)

    def local(self, name: str) -> Path | None:
        """Where the root is on this machine: its first entry that exists (else its first entry)."""
        cands = [p for n, p in self.entries if n == name]
        return next((p for p in cands if p.exists()), cands[0] if cands else None)

    def portable(self, p: Path, resolve: bool = True) -> str:
        p = Path(p).resolve() if resolve else Path(os.path.abspath(p))
        for name, root in self.longest:
            for r in {root, root.resolve()} if resolve else {root}:
                try:
                    rel = p.relative_to(r).as_posix()
                except ValueError:
                    continue
                return f"{name}:{'' if rel == '.' else rel}"
        return p.as_posix()

    def resolve(self, s: str) -> Path | None:
        """A ROOT:path as a path on this machine (None if the root is not configured); other strings as paths."""
        if ":" in s and not s.startswith("/") and not (len(s) > 1 and s[1] == ":" and s[2:3] in ("\\", "/")):
            name, rest = s.split(":", 1)
            base = self.local(name)
            return None if base is None else (base / rest if rest else base)
        return Path(s)

    def is_root(self, p: Path) -> bool:
        p = Path(os.path.abspath(p))
        return any(p == r or p == r.resolve() for _, r in self.entries)


def roots() -> list[tuple[str, Path]]:
    """Named roots (and aliases), longest path first."""
    return Roots.load().longest


def portable(p: Path) -> str:
    return Roots.load().portable(p)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def describe(p: Path, hash_limit: int = HASH_LIMIT, tree_limit: int = TREE_LIMIT, skip: Path | None = None) -> dict:
    """A file or folder's identity: its SHA-256 (tree hash for a folder) or, when too large, a fingerprint."""
    p = Path(p)
    st = p.stat()
    if p.is_file():
        d = {"path": portable(p), "kind": "file", "bytes": st.st_size}
        if st.st_size <= hash_limit:
            d["sha256"] = sha256(p)
        else:
            d["mtime"] = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        return d
    files, unreadable = [], 0
    for q in sorted(p.rglob("*")):
        parts = q.relative_to(p).parts
        if RUNS in parts or ".git" in parts or "__pycache__" in parts or (skip is not None and skip in q.parents):
            continue
        try:
            if q.is_file():
                s = q.stat()
                files.append((q, s.st_size, s.st_mtime))
        except OSError:             # protected or vanished files are counted, not fatal
            unreadable += 1
    d = {"path": portable(p), "kind": "folder", "files": len(files), "bytes": sum(f[1] for f in files)}
    if unreadable:
        d["unreadable"] = unreadable
    tree = None
    if not unreadable and len(files) <= tree_limit and all(f[1] <= hash_limit for f in files):
        try:
            h = hashlib.sha256()
            for q, _, _ in files:
                h.update(f"{q.relative_to(p).as_posix()}\0{sha256(q)}\n".encode())
            tree = h.hexdigest()
        except OSError:
            tree = None
    if tree:
        d["tree_sha256"] = tree
    else:
        d["mtime_newest"] = dt.datetime.fromtimestamp(max((f[2] for f in files), default=0)).isoformat(
            timespec="seconds")
    return d


def git_state(path: Path) -> dict | None:
    """Repository, commit and uncommitted changes for the repository holding path (None outside git)."""
    path = Path(path).resolve()
    where = path if path.is_dir() else path.parent

    def git(*a, strip=True):
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(where), *a], capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return r.stdout.strip() if strip else r.stdout.rstrip("\n")
    top = git("rev-parse", "--show-toplevel")
    if not top:
        return None
    status = git("status", "--porcelain", strip=False) or ""
    changed = [line[3:] for line in status.splitlines()]
    d = {"repo": portable(Path(top)), "commit": git("rev-parse", "HEAD"), "dirty": bool(changed),
         "changed_files": changed[:50]}
    if path.is_file():
        rel = path.relative_to(Path(top).resolve()).as_posix()
        d["file"] = rel
        d["file_changed"] = rel in changed or any(c.endswith(rel) for c in changed)
    return d


def find_script(args: list[str]) -> Path | None:
    """The script a command runs: the first argument naming an existing .py or .sh file."""
    for a in args:
        if a.endswith((".py", ".sh")) and Path(a).is_file():
            return Path(a)
    return None


def inputs_of(args: list[str], out: Path, script: Path | None, program: bool = False, **kw) -> list[dict]:
    """Inputs named on a command line; program=True when args[0] is the program run (not an input)."""
    out = out.resolve()
    R = Roots.load()
    seen, res = set(), []
    for i, a in enumerate(args):
        if program and i == 0:
            continue
        cands = [a]
        if a.startswith("--") and "=" in a:
            cands = [a.split("=", 1)[1]]
        for c in cands:
            if not c or c.startswith("-"):
                continue
            p = Path(c)
            try:
                if not p.exists():
                    continue
                r = p.resolve()
            except OSError:
                continue
            if r == out or out in r.parents or (script is not None and r == script.resolve()) or r in seen:
                continue
            if r == Path("/") or r == Path.home():
                continue
            seen.add(r)
            if R.is_root(r):           # a whole work folder or release: recorded by name, not read
                d = {"path": R.portable(r), "kind": "root", "arg_index": i}
                if i > 0 and args[i - 1].startswith("--") and "=" not in args[i - 1]:
                    d["flag"] = args[i - 1]
                res.append(d)
                continue
            try:
                d = describe(r, skip=out if r in out.parents else None, **kw)
            except OSError as e:
                d = {"path": portable(r), "error": f"{type(e).__name__}: {e}"[:200]}
            d["arg_index"] = i
            if i > 0 and args[i - 1].startswith("--") and "=" not in args[i - 1]:
                d["flag"] = args[i - 1]
            res.append(d)
    return res


def packages() -> list[dict]:
    """Git state of local packages on PYTHONPATH (each entry that is inside a git repository)."""
    out, seen = [], set()
    for e in filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        p = Path(e)
        if p.is_dir():
            g = git_state(p)
            if g and g["repo"] not in seen:
                seen.add(g["repo"])
                out.append(g)
    return out


def outputs_of(out: Path, since: float | None = None, hash_limit: int = HASH_LIMIT) -> list[dict]:
    """Files in the output folder (not _runs or the _runs_* warnings), with SHA-256 up to the hash limit; only those changed since `since`."""
    res = []
    for q in sorted(Path(out).rglob("*")):
        if RUNS in q.relative_to(out).parts or q.name.startswith(RUNS):
            continue
        try:
            if not q.is_file():
                continue
            st = q.stat()
            if since is not None and st.st_mtime < since:
                continue
            d = {"path": portable(q), "bytes": st.st_size}
            if st.st_size <= hash_limit:
                d["sha256"] = sha256(q)
        except OSError as e:
            d = {"path": portable(q), "error": f"{type(e).__name__}"}
        res.append(d)
    return res


def new_record(out: Path, args: list[str], script: Path | None, kind: str, note: str = "",
               extra: list[str] | None = None, program: bool = True, **kw) -> dict:
    """A record for a command (program=True: args[0] is the program) or a driver's arguments (program=False)."""
    script = script or find_script(args)
    ins = inputs_of(args, out, script, program=program, **kw)
    R = Roots.load()
    for e in extra or []:
        if R.is_root(Path(e).resolve()):
            ins.append({"path": R.portable(Path(e)), "kind": "root", "declared": True})
            continue
        try:
            o, r = Path(out).resolve(), Path(e).resolve()
            d = describe(Path(e), skip=o if r in o.parents else None, **kw)
        except OSError as err:
            d = {"path": portable(Path(e)), "error": f"{type(err).__name__}: {err}"[:200]}
        d["declared"] = True
        ins.append(d)
    return {
        "schema": SCHEMA, "kind": kind, "started": now(), "finished": None, "exit_code": None,
        "out": portable(out), "cwd": portable(Path.cwd()), "command": args,
        "script": ({"path": portable(script), "sha256": sha256(script), "git": git_state(script)} if script else None),
        "inputs": ins,
        "packages": packages(),
        "python": platform.python_version(), "host": socket.gethostname(),
        "note": note, "outputs": [],
    }


def write(rec: dict, out: Path) -> Path:
    d = Path(out) / RUNS
    d.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")   # UTC, so names sort across machines
    p = d / f"run_{stamp}_{os.getpid()}.json"
    n = 1
    while p.exists():
        p = d / f"run_{stamp}_{os.getpid()}_{n}.json"
        n += 1
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p


def finish(path: Path, exit_code: int, since: float | None, hash_limit: int = HASH_LIMIT) -> dict:
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    out = Path(path).parent.parent
    rec["finished"] = now()
    rec["exit_code"] = exit_code
    rec["outputs"] = outputs_of(out, since, hash_limit)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return rec


def started_epoch(rec: dict) -> float:
    return dt.datetime.fromisoformat(rec["started"]).timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="provenance", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "begin", "reconstructed"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True, help="the folder the command writes its outputs to")
        p.add_argument("--script", help="the script, when the command does not name it as a file")
        p.add_argument("--note", default="")
        p.add_argument("--input", action="append", default=[],
                       help="an input the command reads without naming it (a fixed path under --work); repeatable")
        p.add_argument("--hash-limit", type=int, default=HASH_LIMIT)
        p.add_argument("--tree-limit", type=int, default=TREE_LIMIT)
        if name == "reconstructed":
            p.add_argument("--output", action="append", default=[],
                           help="an output the run made (repeatable); default: every file in --out")
        p.add_argument("args", nargs=argparse.REMAINDER, help="-- then the command (or, for begin, its arguments)")
    e = sub.add_parser("end")
    e.add_argument("record")
    e.add_argument("--exit-code", type=int, required=True)
    e.add_argument("--hash-limit", type=int, default=HASH_LIMIT)
    s = sub.add_parser("show")
    s.add_argument("folder")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        for p in sorted((Path(a.folder) / RUNS).glob("run_*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            sc = (r.get("script") or {}).get("path")
            g = ((r.get("script") or {}).get("git") or {})
            print(f"{p.name}: {r['kind']} {r['started']} -> {r['finished']} exit {r['exit_code']}; {sc} "
                  f"@{(g.get('commit') or '')[:12]}{' (changed)' if g.get('file_changed') else ''}; "
                  f"{len(r['inputs'])} inputs, {len(r['outputs'])} outputs")
        return 0
    if a.cmd == "end":
        rec = json.loads(Path(a.record).read_text(encoding="utf-8"))
        finish(Path(a.record), a.exit_code, started_epoch(rec) - 1, a.hash_limit)
        return 0

    args = a.args[1:] if a.args[:1] == ["--"] else a.args
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    kw = {"hash_limit": a.hash_limit, "tree_limit": a.tree_limit}
    script = Path(a.script) if a.script else None
    if a.cmd == "reconstructed":
        if not a.note:
            ap.error("reconstructed needs --note saying where the record comes from")
        rec = new_record(out, args, script, "reconstructed", a.note, a.input, **kw)
        rec["started"] = None
        if a.output:
            rec["outputs"] = []
            for o in a.output:
                st = Path(o).stat()
                d = {"path": portable(Path(o)), "bytes": st.st_size}
                if Path(o).is_file() and st.st_size <= a.hash_limit:
                    d["sha256"] = sha256(Path(o))
                rec["outputs"].append(d)
        else:
            rec["outputs"] = outputs_of(out, None, a.hash_limit)
        print(write(rec, out))
        return 0
    try:
        rec = new_record(out, args, script, "recorded", a.note, a.input, program=(a.cmd == "record"), **kw)
    except Exception as e:     # the recorder must never stop the run: write what is known and go on
        print(f"provenance: incomplete record ({type(e).__name__}: {e})", file=sys.stderr)
        rec = {"schema": SCHEMA, "kind": "recorded", "started": now(), "finished": None, "exit_code": None,
               "out": str(out), "command": args, "script": None, "inputs": [], "packages": [], "note": a.note,
               "outputs": [], "record_error": f"{type(e).__name__}: {e}"[:300]}
    path = write(rec, out)
    if a.cmd == "begin":
        print(path)
        return 0
    t0 = started_epoch(rec) - 1
    code = subprocess.call(args)
    finish(path, code, t0, a.hash_limit)
    return code


if __name__ == "__main__":
    sys.exit(main())
