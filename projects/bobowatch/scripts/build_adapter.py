"""Build the standalone adapter from canonical modules, without a source mirror."""

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = (
    "__init__.py",
    "adapter.py",
    "asgi.py",
    "client.py",
    "config.py",
    "paths.py",
    "protocol.py",
    "provision.py",
    "wsgi.py",
)


def build(output, *, allow_dirty=False):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=PROJECT, text=True).strip()

    checkout = Path(git("rev-parse", "--show-toplevel"))
    project_path = PROJECT.relative_to(checkout).as_posix()
    dirty = bool(git("status", "--porcelain", "--", "."))
    if dirty and not allow_dirty:
        raise ValueError(
            "Commit project changes before building a release; use --allow-dirty for QA"
        )
    version = next(
        ast.literal_eval(node.value)
        for node in ast.parse((PROJECT / "bobowatch/__init__.py").read_text()).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    )
    provenance = {
        "schema": 1,
        "version": version,
        "source_repository": "https://github.com/lichen-liu/boboji",
        "source_project": project_path,
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD:" + project_path),
        "uncommitted_changes": dirty,
        "modules_sha256": {
            name: hashlib.sha256((PROJECT / "bobowatch" / name).read_bytes()).hexdigest()
            for name in MODULES
        },
    }
    metadata = f"""[build-system]
requires = ["hatchling==1.32.4"]
build-backend = "hatchling.build"

[project]
name = "boboji-bobowatch-adapter"
version = {json.dumps(version)}
description = "Standard-library BoboWatch adapters and local provisioning"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICENSE"]
dependencies = []

[project.urls]
Source = "https://github.com/lichen-liu/boboji/tree/main/projects/bobowatch"

[tool.hatch.build.targets.wheel]
packages = ["bobowatch"]

[tool.hatch.build.targets.sdist]
include = ["bobowatch", "pyproject.toml", "README.md", "LICENSE"]
"""
    output = output.resolve()
    with tempfile.TemporaryDirectory(prefix="bobowatch-adapter-build-") as directory:
        staging = Path(directory) / "source"
        package = staging / "bobowatch"
        package.mkdir(parents=True)
        for name in MODULES:
            shutil.copyfile(PROJECT / "bobowatch" / name, package / name)
        (package / "_adapter_build.json").write_text(json.dumps(provenance, indent=2) + "\n")
        (staging / "pyproject.toml").write_text(metadata)
        (staging / "README.md").write_text(
            "# BoboWatch adapter\n\n"
            "Python 3.11+ standard-library ASGI/WSGI adapters and same-user provisioning.\n"
            "No collector, database, dashboard, or server dependencies.\n"
            "Importing the adapter does not start monitoring.\n"
        )
        shutil.copyfile(checkout / "LICENSE", staging / "LICENSE")
        artifacts = Path(directory) / "dist"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(artifacts),
                str(staging),
            ],
            check=True,
            env=dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", "HEAD")),
        )
        output.mkdir(parents=True, exist_ok=True)
        result = []
        for artifact in sorted(artifacts.iterdir()):
            destination = output / artifact.name
            if destination.exists() and destination.read_bytes() != artifact.read_bytes():
                raise ValueError("Refusing to replace a different artifact: " + str(destination))
            shutil.copyfile(artifact, destination)
            result.append(
                {
                    "name": destination.name,
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            )
    return {"provenance": provenance, "artifacts": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "var/adapter")
    parser.add_argument(
        "--allow-dirty", action="store_true", help="QA only; records dirty provenance"
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output, allow_dirty=args.allow_dirty), indent=2))


if __name__ == "__main__":
    main()
