"""Reject unpinned actions and elevated or unsafe workflow trigger patterns."""
from pathlib import Path
import re

for file in Path(".github/workflows").glob("*.yml"):
    text = file.read_text()
    for action in re.findall(r"uses:\s*([^\s#]+)", text):
        if action.startswith("./"):
            continue
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action):
            raise SystemExit(f"Unpinned external action: {file}: {action}")
    if "pull_request_target" in text or "workflow_run:" in text:
        raise SystemExit(f"Unsafe privilege-escalation trigger: {file}")
    if "persist-credentials: false" not in text:
        raise SystemExit(f"Checkout credential persistence not explicitly disabled: {file}")
    if "contents: read" not in text:
        raise SystemExit(f"Explicit read-only content permissions missing: {file}")
print("Workflow source checks passed; server-side protections are not asserted.")
