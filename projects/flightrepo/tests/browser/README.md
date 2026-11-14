# Fictional browser checks

From `projects/flightrepo/`, install development dependencies and the locked
browser-only packages:

```sh
python -m pip install -e '.[dev]'
npm ci --prefix tests/browser --ignore-scripts --no-audit --no-fund
tests/browser/node_modules/.bin/playwright install chromium webkit
```

Start `python scripts/run_demo.py --port 8013` in a separate terminal. It uses
the synthetic demo database, never the real hosted or ingestion databases. Then:

```sh
node --test tests/test_*.mjs
NODE_PATH=tests/browser/node_modules FLYJI_QA_BROWSER=chromium node scripts/qa_web.cjs
NODE_PATH=tests/browser/node_modules FLYJI_QA_BROWSER=webkit FLYJI_QA_OUTPUT=var/web-qa/webkit node scripts/qa_web.cjs
```

Stop the fictional demo after checking it. CI manages its own isolated demo
process, installs the Linux browser libraries, and uploads failure screenshots
from this project's ignored `var/` only.
