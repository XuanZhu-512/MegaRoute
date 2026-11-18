"""Runtime installer keeps provenance and refuses destructive unknown replacements."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_tm', ROOT / 'tools/install_tracemaker.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'configs').mkdir()
        self.lock = self.root / 'configs/toolchain.json'
        self.lock.write_text(json.dumps({'executable': '../runtime/bin/tracemaker',
                                        'exact_version': '0.12.1', 'source_commit': 'abc',
                                        'source_url': 'https://github.com/DingoOz/TraceMaker'}))
        self.archive = self.root / 'release.tar.gz'

    def make_archive(self, version='0.12.1'):
        files = {'bin/tracemaker': f'#!{sys.executable}\nprint("tracemaker {version}")\n',
                 'bin/tracemaker-place': 'unused',
                 'share/doc/tracemaker/LICENSE': 'GPL-3.0-or-later',
                 'share/doc/tracemaker/NOTICE': 'upstream notices',
                 'share/doc/tracemaker/README.md': 'upstream readme', 'INSTALL.txt': 'install'}
        with tarfile.open(self.archive, 'w:gz') as tar:
            for relative, data in files.items():
                data = data.encode()
                member = tarfile.TarInfo('tracemaker-0.12.1-linux-x86_64/' + relative)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))

    def test_only_runtime_files_and_licenses_installed_and_hashes_locked(self):
        self.make_archive()
        result = installer.install(self.archive, self.lock)
        runtime = self.root / 'runtime'
        self.assertTrue((runtime / 'bin/tracemaker').is_file())
        self.assertFalse((runtime / 'bin/tracemaker-place').exists())
        self.assertFalse((runtime / '.git').exists())
        self.assertEqual((runtime / 'NOTICE').read_text(), 'upstream notices')
        self.assertEqual(json.loads(self.lock.read_text())['sha256'], result['executable_sha256'])
        (runtime / 'source-build.tar.gz').write_bytes(b'source archive')
        installer.install(self.archive, self.lock)
        self.assertEqual((runtime / 'source-build.tar.gz').read_bytes(), b'source archive')

    def test_wrong_binary_version_does_not_replace_existing_runtime(self):
        self.make_archive()
        installer.install(self.archive, self.lock)
        original = (self.root / 'runtime/bin/tracemaker').read_bytes()
        self.make_archive(version='0.12.2')
        with self.assertRaisesRegex(ValueError, 'Unexpected release version'):
            installer.install(self.archive, self.lock)
        self.assertEqual((self.root / 'runtime/bin/tracemaker').read_bytes(), original)

    def test_unknown_existing_directory_is_preserved(self):
        (self.root / 'runtime').mkdir()
        marker = self.root / 'runtime/user-file'
        marker.write_text('keep')
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'Unknown existing'):
            installer.install(self.archive, self.lock)
        self.assertEqual(marker.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
