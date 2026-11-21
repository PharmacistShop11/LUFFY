#!/usr/bin/env python3
"""One-shot sync: refresh the README Complete TODO List from TODO code markers.

Scope rule: only Python files that differ between ``main`` and ``HEAD`` are
regenerated; every other baseline README row is preserved byte-for-byte.
"""
import pathlib
import re
import subprocess
import sys

ROW_RE = re.compile(
    r"(?m)^- \[ \] \*\*(?P<path>.+?):(?P<line>\d+)\*\* - (?P<text>.*)$"
)
TODO_RE = re.compile(
    r"#\s*TODO(?:\s*\((?P<author>[^)]*)\))?(?P<post>[^\n]*)$", re.IGNORECASE
)
GREP_PATTERN = r"#([[:space:]]*TODO([[:space:]]*\([^)]*\))?[[:space:]]*:?[[:space:]]*)"


def extract_body(content):
    """Convert one source line containing a TODO marker into README row text."""
    m = TODO_RE.search(content)
    if not m:
        return None
    post = m.group("post") or ""
    if m.group("author") is not None:
        return ("(" + m.group("author") + ")" + post).strip()
    return re.sub(r"^\s*:\s*", "", post).strip()


def run(args, cwd, check=True):
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout + "\n" + p.stderr + "\n")
        raise SystemExit("command failed: %s" % " ".join(args))
    return p


def main():
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    main_ref = None
    for cand in ("refs/remotes/origin/main", "origin/main", "main"):
        if run(["git", "rev-parse", "--verify", "--quiet", cand], root, False).returncode == 0:
            main_ref = cand
            break
    if main_ref is None:
        raise SystemExit("main ref not found")

    head = "HEAD"
    changed = sorted(set(
        run(["git", "diff", "--name-only", main_ref + ".." + head, "--", "*.py"], root)
        .stdout.split()
    ))
    print("[info] changed .py files main..HEAD:", changed)
    if not changed:
        raise SystemExit("no changed python files; nothing to update")

    grep = run(
        ["git", "grep", "-n", "-I", "-E", "-e", GREP_PATTERN, head, "--"] + changed,
        root, check=False,
    )
    scanned = {}
    for line in grep.stdout.splitlines():
        first, second = line.find(":"), line.find(":", line.find(":") + 1)
        try:
            path, lineno, content = line[:first], int(line[first + 1:second]), line[second + 1:]
        except ValueError:
            print("[warn] unparsable git grep line:", line[:180])
            continue
        body = extract_body(content)
        if body is None:
            continue
        scanned.setdefault(path, set()).add((lineno, body))
    scanned = {p: sorted(rows) for p, rows in scanned.items()}

    readme = pathlib.Path(root, "README.md")
    raw = readme.read_text(encoding="utf-8")
    hmatch = re.search(r"(?m)^### .*Complete TODO List\s*$", raw)
    fmatch = re.search(r"(?m)^## .*Contributing\s*$", raw)
    if not hmatch or not fmatch or fmatch.start() < hmatch.end():
        raise SystemExit("README section headings not found")

    old_rows = [
        (m.group("path"), int(m.group("line")), m.group("text"))
        for m in ROW_RE.finditer(raw[hmatch.end():fmatch.start()])
    ]
    print("[info] parsed baseline README rows:", len(old_rows))

    final_by_file = {}
    for path, lineno, text in old_rows:
        final_by_file.setdefault(path, []).append((lineno, text))
    for path in changed:
        final_by_file[path] = scanned.get(path, [])

    new_rows = []
    for path, rows in final_by_file.items():
        for lineno, text in rows:
            new_rows.append((path, lineno, text))
    new_rows.sort(key=lambda r: (r[0], r[1]))

    old_outside = sorted(r for r in old_rows if r[0] not in changed)
    new_outside = sorted(r for r in new_rows if r[0] not in changed)
    if old_outside != new_outside:
        raise SystemExit("refusing: README rows outside changed files differ")

    old_set, new_set = set(old_rows), set(new_rows)
    print("[change] added rows:", len(new_set - old_set))
    for row in sorted(new_set - old_set):
        print("  + %s:%s - %s" % row)
    print("[change] removed rows:", len(old_set - new_set))
    for row in sorted(old_set - new_set):
        print("  - %s:%s - %s" % row)

    old_by, new_by = {}, {}
    for p, l, t in old_rows:
        old_by.setdefault(p, []).append((l, t))
    for p, l, t in new_rows:
        new_by.setdefault(p, []).append((l, t))
    for path in changed:
        print("[file] %s: %d -> %d" % (path, len(old_by.get(path, [])), len(new_by.get(path, []))))
        for lineno, text in new_by.get(path, []):
            print("    * %d: %s" % (lineno, text))

    block = "\n".join("- [ ] **%s:%d** - %s" % row for row in new_rows)
    updated = raw[:hmatch.end()] + "\n\n" + block + "\n\n" + raw[fmatch.start():]

    parsed_after = [
        (m.group("path"), int(m.group("line")), m.group("text"))
        for m in ROW_RE.finditer(updated)
    ]
    if len(parsed_after) != len(new_rows) or sorted(parsed_after) != new_rows:
        raise SystemExit("post-write verification failed")
    readme.write_text(updated, encoding="utf-8")

    print("[done] total rows: %d -> %d" % (len(old_rows), len(new_rows)))
    diffstat = run(["git", "diff", "--stat", "--", "README.md"], root, False).stdout
    print(diffstat)


if __name__ == "__main__":
    main()
