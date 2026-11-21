#!/usr/bin/env python3
import collections
import pathlib
import re
import subprocess
import sys

SECTION_RE = re.compile(r'(?m)^###[ \t]+.*Complete TODO List[ \t]*$')
FOOTER_RE = re.compile(r'(?m)^##[ \t]+.*Contributing[ \t]*$')
MARKER_RE = re.compile(r'#([[:space:]]*TODO([[:space:]]*\([^)]*\))?[[:space:]]*:?[[:space:]]*)')
LOCATION = re.compile(r'([A-Za-z0-9_./-]+\.py)\s*:\s*(\d+)')
BOLD_LOCATION = re.compile(r'\*\*\s*([A-Za-z0-9_./-]+\.py)\s*:\s*(\d+)\s*\*\*')
STRICT = re.compile(r'^- \[ \] \*\*(?P<path>.+?):(?P<line>\d+)\*\* - (?P<text>.*)$')
BULLET = re.compile(r'^\s*(?:[-*]|\d+[.)])\s+')
CHANGED_WANT = ('luffy/deepscaler/utils.py', 'luffy/verl/verl/protocol.py')


def run(args, root):
    p = subprocess.run(args, cwd=root, text=True, capture_output=True)
    return p


def main():
    root = run(['git', 'rev-parse', '--show-toplevel'], '.').stdout.strip()
    main_ref = None
    for ref in ('refs/remotes/origin/main', 'origin/main', 'main'):
        if run(['git', 'rev-parse', '--verify', '--quiet', ref], root).returncode == 0:
            main_ref = ref
            break
    changed = run(['git', 'diff', '--name-only', main_ref + '..HEAD', '--', '*.py'], root).stdout.splitlines()
    changed = [x for x in changed if not x.startswith('.github/')]
    print('DIAG changed_py=', changed)
    grep = run(['git', 'grep', '-n', '-I', '-E', '-e', MARKER_RE.pattern, 'HEAD', '--'] + changed, root)
    print('DIAG grep_return=', grep.returncode, 'grep_lines=', len(grep.stdout.splitlines()))
    for line in grep.stdout.splitlines():
        print('DIAG_GREP', line)

    readme_path = pathlib.Path(root) / 'README.md'
    raw = readme_path.read_text(encoding='utf-8')
    h = SECTION_RE.search(raw)
    f = FOOTER_RE.search(raw)
    print('DIAG headings', bool(h), bool(f), repr(h.group(0) if h else None))
    body = raw[h.end():f.start()] if h and f else ''
    lines = body.splitlines()
    print('DIAG body lines', len(lines), 'blank', sum(not x.strip() for x in lines))
    strict=bold=bullet=checked=plain=0
    formats=collections.Counter()
    malformed=[]
    target_rows=[]
    for i,line in enumerate(lines,1):
        if STRICT.match(line): strict += 1
        bm = BOLD_LOCATION.search(line)
        if bm and BULLET.match(line): bold += 1
        if BULLET.match(line): bullet += 1
        if re.match(r'^\s*[-*]\s*\[[xX]\]', line): checked += 1
        if LOCATION.search(line) and BULLET.match(line): plain += 1
        if bm:
            key='bold_bullet_other' if not STRICT.match(line) else 'strict'
            formats[key]+=1
        elif LOCATION.search(line) and BULLET.match(line):
            formats['plain_or_other_bullet_py']+=1
            if len(malformed)<25: malformed.append((i,line[:220]))
        elif BULLET.match(line):
            formats['other_bullet']+=1
            if len(malformed)<25: malformed.append((i,line[:180]))
        if any(x in line for x in CHANGED_WANT):
            target_rows.append((i,line[:240]))
    print('DIAG counts strict bold bullet checked plain=', strict,bold,bullet,checked,plain)
    print('DIAG formats', dict(formats))
    print('DIAG target_rows count', len(target_rows))
    for x in target_rows[:80]: print('DIAG_TARGET_ROW', repr(x))
    print('DIAG malformed first', malformed)
    print('DIAG_DONE')
    raise SystemExit(2)

if __name__ == '__main__':
    main()
