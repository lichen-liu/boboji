"""Verify wheel isolation and rebuildability from its self-contained source archive."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from zipfile import ZipFile

PROBE = r"""
import importlib
import importlib.metadata
import importlib.util
import json
import sys
import threading
from pathlib import Path

before = set(threading.enumerate())
modules = ('adapter', 'asgi', 'client', 'config', 'paths', 'protocol', 'provision', 'wsgi')
for name in ('bobowatch', *('bobowatch.' + value for value in modules)):
    module = importlib.import_module(name)
    assert Path(module.__file__).is_relative_to(Path(sys.prefix)), module.__file__
assert set(threading.enumerate()) == before
for name in ('waitress', 'bobowatch.storage', 'bobowatch.application', 'bobowatch.__main__'):
    assert importlib.util.find_spec(name) is None, name
dist = importlib.metadata.distribution('boboji-bobowatch-adapter')
assert not dist.requires, dist.requires
import bobowatch
assert bobowatch.__version__ == dist.version
provenance = json.loads(Path(bobowatch.__file__).with_name('_adapter_build.json').read_text())
assert not provenance['uncommitted_changes']
assert len(provenance['modules_sha256']) == 9
print(json.dumps({'version': dist.version, 'source_commit': provenance['source_commit'],
                  'isolated_imports': True, 'import_started_threads': False}))
"""


def contents(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def verify(wheel, sdist=None):
    files = contents(wheel)
    provenance = json.loads(files["bobowatch/_adapter_build.json"])
    expected = {"bobowatch/" + name for name in provenance["modules_sha256"]}
    actual = {name for name in files if name.startswith("bobowatch/")}
    assert actual == expected | {"bobowatch/_adapter_build.json"}, actual
    for name, fingerprint in provenance["modules_sha256"].items():
        assert hashlib.sha256(files["bobowatch/" + name]).hexdigest() == fingerprint, name
    with tempfile.TemporaryDirectory(prefix="bobowatch-adapter-verify-") as directory:
        root = Path(directory)
        environment = dict(
            os.environ,
            PYTHONPATH="",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PIP_NO_INDEX="1",
            PIP_NO_CACHE_DIR="1",
            PIP_DISABLE_PIP_VERSION_CHECK="1",
        )
        venv.EnvBuilder(with_pip=True).create(root / "environment")
        python = root / "environment/bin/python"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--no-deps", str(wheel)],
            cwd=root,
            env=environment,
            check=True,
        )
        result = subprocess.check_output(
            [str(python), "-c", PROBE], cwd=root, env=environment, text=True
        )
        report = json.loads(result)
        if sdist:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--quiet",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(root / "rebuilt"),
                    str(sdist),
                ],
                cwd=root,
                env=environment,
                check=True,
            )
            rebuilt = list((root / "rebuilt").glob("*.whl"))
            assert len(rebuilt) == 1
            assert contents(rebuilt[0]) == files, "Source archive rebuilt different wheel contents"
            report["source_archive_rebuild_verified"] = True
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.wheel.resolve(), args.sdist.resolve() if args.sdist else None), indent=2
        )
    )


if __name__ == "__main__":
    main()
