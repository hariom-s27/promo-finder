"""Pre-declared D80 decision; no model calls or scoring-rule changes."""
from collections import Counter


def d80_decision(items):
    if len(items) != 45:
        raise ValueError("D80 requires exactly 45 DEV current/reference items")
    counts = Counter(item.get("aggregate", {}).get("answers", {}).get("standalone") for item in items)
    if set(counts) - {"yes", "no", None}:
        raise ValueError("D80 encountered an invalid aggregate label")
    minority = min(counts["yes"], counts["no"])
    return {"decision": "ADOPT" if minority >= 5 else "REVERT", "expected_items": 45,
            "yes": counts["yes"], "no": counts["no"], "unmeasured": counts[None],
            "minority_items": minority, "required_minority_items": 5,
            "rule": "ADOPT iff the minority standalone item aggregate has at least 5 of the 45 DEV items"}
