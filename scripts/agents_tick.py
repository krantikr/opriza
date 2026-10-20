"""One scheduling pass for every Oprisa desk: sync if due, run due agent jobs,
hand pending events to the agents. Run from cron every 5 minutes, e.g.

    */5 * * * *  cd /app && uv run python scripts/agents_tick.py

or set AGENTS_SCHEDULER=on to have the API process do it.
"""

from __future__ import annotations

import json

from app.kb.jobs import tick_all

if __name__ == "__main__":
    print(json.dumps(tick_all(), default=str, indent=2))
