# Execution conventions

The current tool runs locally for one conversion and then exits. Its deployment
artifact is a Python wheel; CI verifies that wheel in an isolated environment
without development dependencies. Use the [installation guide](../installation/README.md).

Future network services should retain Trip Dollar's applicable boundaries:
shared Python core, separate frontend/server adapters, loopback binding by
default, explicit manual installation and start/stop, private runtime data and
credentials outside Git, and optional monitoring that never exports user input.
Any future service needs its own documented deployment and validation steps.
