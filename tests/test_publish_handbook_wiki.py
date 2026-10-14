"""Exercise actual Git workflows without touching GitHub or credentials."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publisher', ROOT/'scripts/publish_handbook_wiki.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

def run(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.rstrip('\n')

class WikiPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root/'remote.git'
        self.remote.mkdir()
        run(self.remote, 'init', '--bare', '--initial-branch=main')
        self.seed = self.root/'seed'
        run(self.root, 'clone', str(self.remote), str(self.seed))
        run(self.seed, 'config', 'user.name', 'Wiki Test')
        run(self.seed, 'config', 'user.email', 'wiki@example.test')
        (self.seed/'Home.md').write_text(publisher.MARKER+'\nInitial managed home\n')
        (self.seed/'Unrelated.md').write_text('Existing independent wiki page\n')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'initial wiki')
        run(self.seed, 'push', 'origin', 'main')
        self.target = self.root/'wiki'
        run(self.root, 'clone', str(self.remote), str(self.target))
        run(self.target, 'config', 'user.name', 'Wiki Test')
        run(self.target, 'config', 'user.email', 'wiki@example.test')
        self.source = self.root/'source'
        self.source.mkdir()
        for name in ('Home', 'DE-Start', 'EN-Start'):
            (self.source/f'{name}.md').write_text(publisher.MARKER+f'\nNew {name}\n')
        self.patchers = [patch.object(publisher, 'REMOTE', str(self.remote)),
                         patch.object(publisher, 'SOURCE', self.source)]
        for p in self.patchers:
            p.start(); self.addCleanup(p.stop)

    def update(self, publish=False):
        with contextlib.redirect_stdout(io.StringIO()):
            publisher.update(self.target, publish=publish, remote=str(self.remote))

    def test_prepare_then_publish_preserves_unrelated_pages(self):
        old = run(self.remote, 'rev-parse', 'main')
        self.update()
        self.assertEqual(run(self.remote, 'rev-parse', 'main'), old)
        self.assertEqual((self.target/'Unrelated.md').read_text(), 'Existing independent wiki page\n')
        self.update(publish=True)
        self.assertNotEqual(run(self.remote, 'rev-parse', 'main'), old)
        self.assertEqual(run(self.remote, 'show', 'main:EN-Start.md'),
                         (self.source/'EN-Start.md').read_text().rstrip('\n'))
        self.assertEqual(run(self.target, 'status', '--porcelain'), '')

    def test_refuses_unowned_navigation_before_copying_pages(self):
        (self.target/'Home.md').write_text('Independent home\n')
        run(self.target, 'add', 'Home.md')
        run(self.target, 'commit', '-m', 'independent navigation')
        run(self.target, 'push', 'origin', 'main')
        with self.assertRaisesRegex(RuntimeError, 'unowned'):
            self.update()
        self.assertFalse((self.target/'DE-Start.md').exists())
        self.assertEqual((self.target/'Home.md').read_text(), 'Independent home\n')

    def test_refuses_unrelated_local_changes(self):
        (self.target/'Unrelated.md').write_text('Uncommitted user edit\n')
        with self.assertRaisesRegex(RuntimeError, 'other than'):
            self.update(publish=True)
        self.assertEqual((self.target/'Unrelated.md').read_text(), 'Uncommitted user edit\n')

    def test_stops_when_remote_changes_after_preparation(self):
        self.update()
        (self.seed/'Unrelated.md').write_text('New upstream edit\n')
        run(self.seed, 'add', 'Unrelated.md')
        run(self.seed, 'commit', '-m', 'concurrent wiki update')
        run(self.seed, 'push', 'origin', 'main')
        with self.assertRaisesRegex(RuntimeError, 'Remote changed'):
            self.update(publish=True)
        self.assertEqual(run(self.remote, 'show', 'main:Unrelated.md'), 'New upstream edit')

    def test_rejects_wrong_repository(self):
        run(self.target, 'remote', 'set-url', 'origin', 'https://github.com/example/wrong.wiki.git')
        with self.assertRaisesRegex(RuntimeError, 'origin'):
            self.update(publish=True)

    def test_repository_links_become_wiki_routes(self):
        (self.source/'DE-Start.md').write_text(publisher.MARKER+'\n[English](EN-Start.md)\n')
        self.update()
        self.assertIn('[English](EN-Start)', (self.target/'DE-Start.md').read_text())
        self.update(publish=True)
        self.assertIn('[English](EN-Start)', run(self.remote, 'show', 'main:DE-Start.md'))

if __name__ == '__main__':
    unittest.main()
