#!/usr/bin/env python3
"""Check paired wiki pages, links and known private-original identifiers."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / 'docs/handbook/wiki'
MARK = '<!-- bergen-platform-handbook: managed -->'
FORBIDDEN = [r'192\.168\.\d+\.\d+', r'10\.\d+\.\d+\.\d+',
             r'172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+',
             r'\b(?:[A-Za-z0-9-]+\.)+(?:net|de|cloud|intern)\b',
             r'\bSeite\s+\d+\b', r'\[\[(?:FORM_|MAP)', r'-----BEGIN .*PRIVATE KEY-----',
             r'ssh-ed25519\s+[A-Za-z0-9+/]{40,}']

def check():
    errors = []
    pages = {p.stem: p for p in WIKI.glob('*.md')}
    de = {p[3:] for p in pages if p.startswith('DE-')}
    en = {p[3:] for p in pages if p.startswith('EN-')}
    if de != en:
        errors.append(f'Unpaired language pages: {de ^ en}')
    if len(de) != 13:
        errors.append(f'Expected 13 pages per language, got {len(de)}')
    for stem, p in pages.items():
        text = p.read_text(encoding='utf-8')
        if MARK not in text:
            errors.append(f'{p.name}: missing ownership marker')
        if text.count('```') % 2:
            errors.append(f'{p.name}: unclosed code fence')
        for pattern in FORBIDDEN:
            if re.search(pattern, text, re.I):
                errors.append(f'{p.name}: private-original or unresolved pattern {pattern}')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', '#')):
                continue
            name = target.split('#', 1)[0].removesuffix('.md')
            if name not in pages:
                errors.append(f'{p.name}: missing wiki target {target}')
        if stem.startswith(('DE-', 'EN-')):
            other = ('EN-' if stem.startswith('DE-') else 'DE-')+stem[3:]
            if f']({other}.md)' not in text:
                errors.append(f'{p.name}: missing language switch')
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('|') and (i == 0 or not lines[i-1].startswith('|')):
                if i+1 >= len(lines) or not re.fullmatch(r'\|[\s|:\-]+', lines[i+1]):
                    errors.append(f'{p.name}: table lacks Markdown separator')
    for lang in ('DE', 'EN'):
        pdf = ROOT / f'docs/handbook/print/Emergency-Secrets-{lang}.pdf'
        if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
            errors.append(f'Missing printable template: {pdf.name}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Handbook passed: {len(pages)} wiki pages, {len(de)} aligned language pairs, '
          'valid internal links, blank PDF assets and no known private-original identifiers.')

if __name__ == '__main__':
    check()
