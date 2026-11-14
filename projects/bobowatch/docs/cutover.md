# Deploy BoboWatch from Boboji and verify live senders

The service runs from an installed snapshot outside either source checkout.
Source changes take effect only through an explicit reinstall. Keep the existing
private runtime, endpoint, inventory, credentials, quota, and RAM volume so
existing producers reconnect to the replacement process.

## Replace the monitor process

Use the checked, clean `main` revision and the project's Python 3.11+ environment.
The deployment command stops the old managed process, installs the Boboji source,
starts the replacement, and checks storage. A failed install stays stopped;
rerun a successful deployment before starting after an incomplete install.

```sh
cd /Users/lichen/p/boboji
git switch main
git pull --ff-only
cd projects/bobowatch
watch_runtime="$HOME/Library/Application Support/fyi.boboji.watch"
PATH="$PWD/.venv/bin:$PATH" ./deployment/watch deploy --runtime-dir "$watch_runtime"
./deployment/watch check --runtime-dir "$watch_runtime"
./deployment/watch status --runtime-dir "$watch_runtime"
curl --fail http://127.0.0.1:8720/health
curl --fail http://127.0.0.1:8720/ready
```

The equivalent separate operator steps are `watch stop`, project Python running
`installation/install.py`, then `watch start`, using the same runtime throughout.
Never release the RAM volume to change a source checkout. The existing address
`http://127.0.0.1:8720` now serves the new process, so a second listener or HTTP
redirect is unnecessary.

## Re-apply live application connections

For the existing monitoring-enabled Flightrepo and Trip Dollar servers, these
commands provision/reuse the same replica credentials and update the live sender
configuration without restarting the applications:

```sh
watch_runtime="$HOME/Library/Application Support/fyi.boboji.watch"
/Users/lichen/p/flightrepo/deployment/flyji monitoring --bobowatch-runtime-dir "$watch_runtime"
/Users/lichen/p/trip_dollar/deployment/trip-split monitoring --bobowatch-runtime-dir "$watch_runtime"
```

A server whose monitoring was disabled at process startup requires an explicit
application restart to enable its sender. These two installed servers already
have monitoring enabled. Do not change their replica identities or copy tokens
into commands. Reconfiguration preserves their database and application settings.

Verify both replicas show reports received after the monitor's new process
start, observe more than one reporting interval, and check that only one process
listens on port 8720. Confirm the install receipt identifies Boboji, installed
file hashes validate, readiness passes, and the RAM epoch/private controls match
the pre-deployment state. Use private operator output; do not export observations
or credentials into source control.

## Old checkout and remote archive

The old checkout is not a deployment dependency once the new process, launchd
job, source receipt, both live senders, and saved Git refs have been verified.
Preserve the verified private migration bundles and any local-only work before
removing `/Users/lichen/p/bobowatch`. Keep the installed runtime under Application
Support and Boboji's ignored `var/` backups.

The original GitHub repository is already archived. Retain that archive for old
commit/PR links and historical consumer submodule pins. Removing the local clone
and permanently deleting the GitHub repository are separate cleanup decisions;
current operation does not require permanent deletion of the remote archive.
