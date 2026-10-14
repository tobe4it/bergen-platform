#!/usr/bin/env python3
"""Prepare a bounded wiki update; push only with an explicit --publish."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/handbook/wiki'
REMOTE = 'https://github.com/tobe4it/bergen-platform.wiki.git'
SSH_REMOTE = 'git@github.com:tobe4it/bergen-platform.wiki.git'
MARKER = '<!-- bergen-platform-handbook: managed -->'

def git(target, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-C', str(target), *args], capture_output=True,
                            text=True, stdin=subprocess.DEVNULL, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Git operation failed')
    return result.stdout.rstrip('\n')

def ensure_owned(destination):
    if destination.exists() and MARKER not in destination.read_text(encoding='utf-8'):
        raise RuntimeError(f'Refusing to replace unowned wiki page: {destination.name}')

def source_pages():
    pages = sorted(SOURCE.glob('*.md'))
    if not pages or any(MARKER not in p.read_text(encoding='utf-8') for p in pages):
        raise RuntimeError('Missing or unmarked handbook source pages')
    return pages

def wiki_bytes(page):
    """Use .md links in the main repository and extensionless wiki routes."""
    text = page.read_text(encoding='utf-8')
    text = re.sub(r'\]\(((?:DE|EN)-[A-Za-z0-9-]+|Home)\.md\)', r'](\1)', text)
    return text.encode('utf-8')

def changed_paths(target):
    # --porcelain -z avoids ambiguous filenames and rename parsing. Only simple
    # root-level managed Markdown names are ever accepted for publication.
    output = git(target, 'status', '--porcelain=v1', '-z')
    paths = []
    for entry in output.split('\0'):
        if not entry:
            continue
        if len(entry) < 4 or entry[:2].strip() in ('R', 'C'):
            raise RuntimeError('Unsupported change in wiki checkout')
        paths.append(entry[3:])
    return paths

def update(target, publish=False, remote=REMOTE):
    if remote not in (REMOTE, SSH_REMOTE):
        raise RuntimeError('Unexpected wiki remote; repository identity must match')
    pages = source_pages()
    expected = {p.name: wiki_bytes(p) for p in pages}
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        git(target.parent, 'clone', '--', remote, str(target))
    if not (target/'.git').exists():
        raise RuntimeError('Target is not a standalone wiki checkout')
    if git(target, 'remote', 'get-url', 'origin') not in (REMOTE, SSH_REMOTE):
        raise RuntimeError('Target origin is not the Bergen Platform wiki')
    branch = git(target, 'symbolic-ref', '--short', 'HEAD')
    remote_head = git(target, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
    if branch != remote_head.removeprefix('origin/'):
        raise RuntimeError('Wiki checkout must use its default branch')
    dirty = changed_paths(target)
    for name in dirty:
        path = target/name
        if name not in expected or not path.is_file() or path.read_bytes() != expected[name]:
            raise RuntimeError('Wiki has changes other than the exact prepared handbook output')
    git(target, 'fetch', 'origin')
    if dirty:
        if git(target, 'rev-parse', 'HEAD') != git(target, 'rev-parse', remote_head):
            raise RuntimeError('Remote changed after preparation; resolve before publication')
    else:
        git(target, 'merge', '--ff-only', remote_head)
    for page in pages:
        ensure_owned(target/page.name)
    for page in pages:
        (target/page.name).write_bytes(expected[page.name])
    changes = changed_paths(target)
    if any(name not in expected for name in changes):
        raise RuntimeError('Unexpected changed path; refusing to publish')
    print(git(target, 'diff', '--stat'))
    print(git(target, 'status', '--short'))
    if not publish:
        print('Prepared only. Review the diff; rerun with --publish to commit and push.')
        return
    if not changes:
        print('Wiki already matches the handbook; nothing to publish.')
        return
    git(target, 'add', '--', *sorted(changes))
    git(target, 'commit', '-m', 'docs: publish bilingual user handbook')
    git(target, 'push', 'origin', f'HEAD:refs/heads/{branch}')
    print('Published handbook pages to the wiki default branch.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--remote', default=REMOTE, choices=(REMOTE, SSH_REMOTE))
    args = parser.parse_args()
    target = args.target.expanduser().resolve()
    if target == ROOT or ROOT in target.parents:
        parser.error('Use a separate sibling wiki checkout, not a directory in the source repository')
    try:
        update(target, args.publish, args.remote)
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
        print(f'Wiki update stopped: {error}', file=sys.stderr)
        print('An initialized wiki and authenticated Git write access are required. '
              'Create the first wiki page on GitHub if needed; do not force-push or add tokens to commands.',
              file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
