#!/usr/bin/env python3
"""Install the pinned release as a small external tool, not a nested Git repo.

The archive must be downloaded from the release URL in the toolchain lock.
An existing clean source checkout is packed into source-build.tar.gz before
replacement. A dirty checkout or unknown directory is never pruned.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


BENCH = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(archive, lock_path=BENCH / 'configs/tracemaker-toolchain.json'):
    lock_path = Path(lock_path).resolve()
    lock = json.loads(lock_path.read_text())
    version = lock['exact_version']
    destination = (lock_path.parent / lock['executable']).resolve().parents[1]
    expected = lock['source_commit']
    source = destination if (destination / '.git').is_dir() else None
    if source:
        commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
        if commit != expected or dirty.strip():
            raise ValueError('TraceMaker source checkout differs from the pinned clean commit; refusing to prune')
    elif destination.exists():
        manifest = destination / 'manifest.json'
        if not manifest.is_file() or json.loads(manifest.read_text()).get('source_commit') != expected:
            raise ValueError('Unknown existing TraceMaker directory; refusing to overwrite')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tracemaker-install-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'runtime'
        stage.mkdir()
        prefix = f'tracemaker-{version}-linux-x86_64/'
        keep = {'bin/tracemaker': 'bin/tracemaker',
                'share/doc/tracemaker/LICENSE': 'LICENSE',
                'share/doc/tracemaker/NOTICE': 'NOTICE',
                'share/doc/tracemaker/README.md': 'UPSTREAM_README.md',
                'INSTALL.txt': 'UPSTREAM_INSTALL.txt'}
        with tarfile.open(archive, 'r:gz') as tar:
            for member_name, relative in keep.items():
                member = tar.getmember(prefix + member_name)
                if not member.isfile():
                    raise ValueError(f'Expected a regular release file: {member.name}')
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
        executable = stage / 'bin/tracemaker'
        executable.chmod(0o755)
        proc = subprocess.run([str(executable), 'version'], capture_output=True, text=True, timeout=15, check=True)
        if proc.stdout.strip() != f'tracemaker {version}':
            raise ValueError(f'Unexpected release version: {proc.stdout!r}')
        source_archive = stage / 'source-build.tar.gz'
        if source:
            with tarfile.open(source_archive, 'w:gz') as tar:
                for relative in ('src', 'cmake', 'CMakeLists.txt', 'CMakePresets.json', 'LICENSE', 'NOTICE', 'README.md'):
                    tar.add(source / relative, arcname=f'TraceMaker-{expected}/{relative}')
        elif (destination / source_archive.name).is_file():
            shutil.copy2(destination / source_archive.name, source_archive)
        archive_hash = digest(Path(archive))
        binary_hash = digest(executable)
        manifest = {'schema_version': '1.0', 'version': version,
                    'source_url': lock['source_url'], 'source_commit': expected,
                    'release_url': f'{lock["source_url"]}/releases/download/v{version}/tracemaker-{version}-linux-x86_64.tar.gz',
                    'release_archive_sha256': archive_hash, 'executable_sha256': binary_hash,
                    'license': 'GPL-3.0-or-later', 'cpu_only': True,
                    'runtime': ['bin/tracemaker', 'LICENSE', 'NOTICE'],
                    'rebuild_source_archive': source_archive.name if source_archive.exists() else None}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (stage / 'README.md').write_text(
            f'# TraceMaker {version} external runtime\n\n'
            'CPU-only upstream release; no nested Git repository.\n'
            '`bin/tracemaker` is the only executable used by the benchmark.\n'
            'LICENSE, NOTICE and manifest.json retain licensing and provenance.\n'
            'source-build.tar.gz retains the original CMake/source files for rebuilding\n'
            'with TM_BUILD_TESTS=OFF and TM_BUILD_PYTHON=OFF; upstream dependencies\n'
            f'are required. It is not loaded at runtime. See {BENCH.name}/docs/TRACEMAKER.md.\n')
        backup = Path(tmp) / 'previous'
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
        lock.update(sha256=binary_hash, release_archive_sha256=archive_hash)
        temporary_lock = lock_path.with_suffix('.json.tmp')
        temporary_lock.write_text(json.dumps(lock, indent=2) + '\n')
        os.replace(temporary_lock, lock_path)
        return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.archive), indent=2))
