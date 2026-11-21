#!/usr/bin/env python3
"""Fix/refresh README Complete TODO List for the dev implementation commit.

Cross-checks actual TODO code markers (git grep) and rewrites only the two
main->dev touched groups; every other README row is preserved.
"""
import json
import pathlib
import re
import subprocess
import sys

ROW_RE = re.compile(r"(?m)^- \[ \] \*\*(?P<path>.+?):(?P<line>\d+)\*\* - (?P<text>.*)$")
TODO_RE = re.compile(r"#\s*TODO(?:\s*\((?P<author>[^)]*)\))?(?P<post>[^\n]*)$", re.IGNORECASE)
GREP_PATTERN = r"#([[:space:]]*TODO([[:space:]]*\([^)]*\))?[[:space:]]*:?[[:space:]]*)"
GROUP_PATHS = [
    "luffy/deepscaler/utils.py",
    "luffy/verl/verl/protocol.py",
]
EXPECTED_GROUPS = {
 "luffy/deepscaler/utils.py": [
  [45,"Add logging for API calls and errors"],
  [46,"Support batch processing for multiple prompts"],
  [47,"Add timeout configuration for API calls"],
  [107,"Implement Vertex AI initialization and authentication"],
  [108,"Configure safety settings for content generation"],
  [109,"Set up GenerativeModel with proper system instructions"],
  [110,"Implement retry logic with exponential backoff"],
  [111,"Add comprehensive error handling for API access issues"],
  [112,"Handle rate limiting and quota management"],
  [113,"Implement response validation and text extraction"],
  [114,"Add support for different generation configurations"]
 ],
 "luffy/verl/verl/protocol.py": [
  [114,"Optimize memory usage during tensor reshaping"],
  [115,"Add support for different tensor types and shapes"],
  [136,"Optimize tensor view operations for performance"],
  [137,"Add error handling for invalid batch dimensions"],
  [169,"(zhangchi.usc1992) add consistency check"],
  [265,"we can actually lift this restriction if needed"],
  [351,"(zhangchi.usc1992) whether to copy"]
 ]
}


def extract_body(content):
    m = TODO_RE.search(content)
    if not m:
        return None
    post = m.group("post") or ""
    if m.group("author") is not None:
        return ("(" + m.group("author") + ")" + post).strip()
    return re.sub(r"^\s*:\s*", "", post).strip()


def parse_grep_lines(stdout):
    rows = {}
    for line in stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) == 4:
            _rev, path, lineno_s, content = parts
        elif len(parts) == 3:
            path, lineno_s, content = parts
        else:
            print("[warn] unparsable line:", line[:180]); continue
        try:
            lineno = int(lineno_s)
        except ValueError:
            print("[warn] bad line number:", line[:180]); continue
        body = extract_body(content)
        if body is None:
            continue
        rows.setdefault(path, set()).add((lineno, body))
    return {p: sorted(v) for p, v in rows.items()}


def run(args, cwd, check=True):
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout + "\n" + p.stderr + "\n")
        raise SystemExit("command failed: %s" % " ".join(args))
    return p


def main():
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    main_ref = None
    for cand in ("refs/remotes/origin/main", "origin/main", "main"):
        if run(["git", "rev-parse", "--verify", "--quiet", cand], root, False).returncode == 0:
            main_ref = cand; break
    if main_ref is None:
        raise SystemExit("main ref not found")
    changed = sorted({p for p in run(
        ["git", "diff", "--name-only", main_ref + "..HEAD", "--", "*.py"], root).stdout.split()
        if not p.startswith(".github/")})
    print("[info] changed source files vs main:", changed)

    grep = run(["git", "grep", "-n", "-I", "-E", "-e", GREP_PATTERN, "HEAD", "--"] + GROUP_PATHS,
              root, check=False)
    scanned = parse_grep_lines(grep.stdout)
    expected = {p: [tuple(x) for x in rows] for p, rows in EXPECTED_GROUPS.items()}
    for path in GROUP_PATHS:
        got = scanned.get(path, [])
        print("[scan] %s -> %d markers" % (path, len(got)))
        for row in got:
            print("    * %d: %s" % row)
        if got != expected[path]:
            print("[error] scanned markers do not match EXPECTED_GROUPS for", path)
            print("got:", json.dumps(got, ensure_ascii=False, indent=1))
            print("expected:", json.dumps(expected[path], ensure_ascii=False, indent=1))
            raise SystemExit(2)

    readme = pathlib.Path(root, "README.md")
    raw = readme.read_text(encoding="utf-8")
    hmatch = re.search(r"(?m)^### .*Complete TODO List\s*$", raw)
    fmatch = re.search(r"(?m)^## .*Contributing\s*$", raw)
    if not hmatch or not fmatch:
        raise SystemExit("README headings missing")
    current = [(m.group("path"), int(m.group("line")), m.group("text"))
               for m in ROW_RE.finditer(raw[hmatch.end():fmatch.start()])]
    print("[info] current README rows:", len(current))

    kept = [r for r in current if r[0] not in GROUP_PATHS]
    replaced = list(kept)
    for path in GROUP_PATHS:
        replaced.extend((l, t) for l, t in expected[path])
    replaced.sort(key=lambda r: (r[0], r[1]))

    kept_current = sorted(r for r in current if r[0] not in GROUP_PATHS)
    kept_new = sorted(r for r in replaced if r[0] not in GROUP_PATHS)
    assert kept_new == kept_current, "non-target rows changed unexpectedly"
    assert len(replaced) == len(kept) + sum(len(v) for v in expected.values())
    assert len(replaced) == 215, len(replaced)

    block = "\n".join("- [ ] **%s:%d** - %s" % r for r in replaced)
    updated = raw[:hmatch.end()] + "\n\n" + block + "\n\n" + raw[fmatch.start():]
    after = [(m.group("path"), int(m.group("line")), m.group("text")) for m in ROW_RE.finditer(updated)]
    assert sorted(after) == replaced and len(after) == 215
    for path in GROUP_PATHS:
        grp = [(l, t) for p, l, t in after if p == path]
        assert [r[0] for r in grp] == sorted(r[0] for r in grp)
        print("[final] %s %d rows" % (path, len(grp)))
    readme.write_text(updated, encoding="utf-8")
    print("[done] rows %d -> %d" % (len(current), len(replaced)))
    print(run(["git", "diff", "--stat", "--", "README.md"], root, False).stdout)


if __name__ == "__main__":
    main()
