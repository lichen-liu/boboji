# Adapter distribution for standalone consumers

The `boboji-bobowatch-adapter` distribution provides the existing `bobowatch`
Python imports, ASGI/WSGI instrumentation, and same-user provisioning. It has no
third-party runtime dependencies and contains no collector storage, dashboard,
or daemon. Importing it starts no monitoring or threads. It supports Python
3.11+ on the same macOS/Linux platforms as the source adapter.

Canonical modules live only in `bobowatch/`. The explicit module allowlist and
release tooling live in `scripts/`; builds stage temporary files rather than
maintaining a second source tree. The built wheel and sdist include source
provenance, checksums, version, and MIT license information.

## Build and verify

Use a clean, committed Boboji checkout after its checks pass. From this project:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/build_adapter.py --output var/adapter
.venv/bin/python scripts/verify_adapter.py var/adapter/*.whl --sdist var/adapter/*.tar.gz
```

The verifier installs the wheel into an empty virtualenv outside the checkout,
checks every adapter import, absence of collector/server dependencies and
import-time threads, and rebuilds the wheel's complete contents from the sdist
without a source checkout. `--allow-dirty` builds are QA-only and intentionally
fail release verification. Never overwrite a released artifact with new bytes.

## Explicit release

After the PR is merged and CI passes, build again from the merged commit and
verify it. Explicitly create a Boboji release named `bobowatch-adapter/vVERSION`
at that commit and attach the verified wheel and sdist plus their SHA-256
checksums. Verify the downloaded public artifacts against those checksums.
The existing label/main test triggers do not publish or deploy releases.

Consumers pin the released wheel's full URL and SHA-256 in a PEP 508 dependency.
Keep the distribution name `boboji-bobowatch-adapter`; imports remain `bobowatch`.
The release asset is a normal pinned package dependency, without a package
registry or another editable repository.

Remove the consumer's former `vendor/bobowatch` submodule, wheel force-includes,
and dev/test import-path entries when adopting the dependency. Install only one
owner of the `bobowatch` import namespace: an old application wheel that embeds
the files must be replaced before using the new dependency. Build/probe the
consumer outside the checkout, test monitoring enabled/disabled and startup
failure isolation, and verify clean upgrades. Keep existing runtime settings,
tokens, replica IDs, and protocol unchanged.

Flightrepo and Trip Dollar's historical pins remain available in the archived
source repository. A future version change needs a new release and consumer PR;
archived pins do not receive updates. Upgrade the collector before adopting a
future adapter protocol version that requires it.
