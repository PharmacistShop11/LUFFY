#!/usr/bin/env python3
import json, pathlib, re, subprocess, sys

SECTION_RE = r"(?m)^###[ \t]+[^\n]*Complete TODO List[ \t]*$"
FOOTER_RE = r"(?m)^##[ \t]+[^\n]*Contributing[ \t]*$"
TODO_RE = re.compile(r"#\s*TODO(?:\s*\((?P<author>[^)]*)\))?\s*:?\s*(?P<post>[^\n]*)$", re.I)
ROW_KEY_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s*\*\*(?P<path>.*?):(?P<line>\d+)\*\*(?P<tail>.*)$")
GREP_RE = r"#([[:space:]]*TODO([[:space:]]*\([^)]*\))?[[:space:]]*:?[[:space:]]*)"
COMMENT_RE = re.compile(r"^(?:[^:]+:)?(?P<path>[^:]+):(?P<line>\d+):(?P<text>.*)$")

def run(args, root, check=True):
    p = subprocess.run(args, cwd=root, text=True, capture_output=True)
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout + "\n" + p.stderr + "\n")
        raise SystemExit("command failed: " + " ".join(args))
    return p

def main_ref(root):
    for ref in ("refs/remotes/origin/main", "origin/main", "main"):
        if run(["git", "rev-parse", "--verify", "--quiet", ref], root, False).returncode == 0:
            return ref
    raise SystemExit("main ref not found")

def changed_python(root, main):
    paths = set()
    for spec in ("*.py", ":(glob)**/*.py"):
        out = run(["git", "diff", "--name-only", main + "..HEAD", "--", spec], root).stdout
        for p in out.splitlines():
            p = p.strip()
            if not p.lower().endswith(".py"):
                continue
            parts = pathlib.PurePosixPath(p).parts
            if (parts and parts[0] == ".github") or "__pycache__" in parts:
                continue
            if pathlib.Path(root, p).is_file():
                paths.add(p)
    return sorted(paths)

def parse_marker(line):
    m = TODO_RE.search(line)
    if not m:
        return None
    post = (m.group("post") or "").strip()
    if m.group("author") is not None:
        a = m.group("author").strip()
        return "(" + a + ")" + ((" " + post) if post else "")
    return post

def scan(root, changed):
    if not changed:
        return {}
    g = run(["git", "grep", "-n", "-I", "-E", "-e", GREP_RE, "HEAD", "--"] + changed, root, False)
    rows = {}
    for line in g.stdout.splitlines():
        m = COMMENT_RE.match(line)
        if not m:
            print("[warn] unparsable grep line", line[:160]); continue
        body = parse_marker(m.group("text"))
        if body is None:
            continue
        rows.setdefault(m.group("path"), set()).add((int(m.group("line")), body))
    return {p: sorted(v) for p, v in rows.items()}

def render(path, line, text):
    return "- [ ] **%s:%d** - %s" % (path, line, text)

def parse_rows(raw):
    out = []
    hm = re.search(SECTION_RE, raw); fm = re.search(FOOTER_RE, raw)
    for line in raw[hm.end():fm.start()].splitlines():
        m = ROW_KEY_RE.match(line)
        if m:
            text = m.group("tail")
            if text.startswith(" - "):
                text = text[3:]
            out.append((m.group("path"), int(m.group("line")), text.strip()))
    return out

def transform(raw, changed, scanned):
    hm = re.search(SECTION_RE, raw); fm = re.search(FOOTER_RE, raw)
    if not hm or not fm or fm.start() < hm.end():
        raise SystemExit("Complete TODO section or Contributing footer heading not found")
    title = raw[hm.start():hm.end()]
    assert title == "### 📝 Complete TODO List", repr(title)
    middle = raw[hm.end():fm.start()]
    lines = middle.splitlines()
    records, anomalies, first_rec = [], [], None
    for idx, line in enumerate(lines):
        m = ROW_KEY_RE.match(line)
        if not m:
            if line.strip() and first_rec is not None:
                anomalies.append(line.rstrip())
            continue
        if first_rec is None:
            first_rec = idx
        records.append({"path": m.group("path"), "line": int(m.group("line")), "raw": line.rstrip()})
    if anomalies:
        raise SystemExit("non-bullet content inside list after first row: " + repr(anomalies[:3]))
    kept, removed = [], []
    target_set = set(changed)
    for rec in records:
        if rec["path"] in target_set:
            removed.append((rec["path"], rec["line"], rec["raw"]))
        else:
            kept.append(rec)
    items = [((r["path"], r["line"]), 0, r["raw"]) for r in kept]
    targets = []
    for p in changed:
        for line, text in scanned.get(p, []):
            targets.append((p, line, text))
            items.append(((p, line), 1, render(p, line, text)))
    items.sort(key=lambda z: (z[0][0], z[0][1], z[1]))
    bullets = [z[2] for z in items]
    new_middle = "\n\n" + "\n".join(bullets) + "\n\n"
    updated = raw[:hm.end()] + new_middle + raw[fm.start():]
    assert updated.count("### 📝 Complete TODO List") == 1
    keys = [(p, l) for p, l, _ in parse_rows(updated)]
    assert keys == sorted(keys), "README TODO rows are not globally sorted"
    for p in changed:
        got = [(l, t) for pp, l, t in parse_rows(updated) if pp == p]
        assert got == scanned.get(p, []), (p, got, scanned.get(p, []))
    stats = {"old_records": len(records), "kept": len(kept), "removed_old_target_rows": len(removed),
             "target_rows": len(targets), "total_final_records": len(keys), "changed_files": changed}
    return updated, stats

def main():
    root = run(["git", "rev-parse", "--show-toplevel"], ".").stdout.strip()
    main = main_ref(root)
    changed = changed_python(root, main)
    print("[info] main ref", main)
    print("[info] changed source files main..HEAD:", changed)
    scanned = scan(root, changed)
    for p, rows in scanned.items():
        print("[scan] %s: %d" % (p, len(rows)))
        for l, t in rows:
            print("    * %d: %s" % (l, t))
    readme = pathlib.Path(root, "README.md")
    raw = readme.read_text(encoding="utf-8")
    updated, stats = transform(raw, changed, scanned)
    print("[stats]", json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if updated == raw:
        print("[done] README TODO section already current; no README change")
        return
    readme.write_text(updated, encoding="utf-8")
    print("[done] README.md TODO section rewritten")
    print(run(["git", "diff", "--stat", "--", "README.md"], root, False).stdout)

if __name__ == "__main__":
    main()
