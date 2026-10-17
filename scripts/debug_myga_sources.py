#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): run the new MYGA fetcher
against the live market and print what it would publish."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_myga as fm  # noqa: E402

fm.OUT.unlink(missing_ok=True)
print("status:", fm.fetch_myga())
d = json.loads(fm.OUT.read_text())
print(json.dumps({k: v for k, v in d.items() if k not in ("buckets", "overall")}, indent=1))
for key, b in d.get("buckets", {}).items():
    print(f"{b['label']:>9}: " + "  ".join(
        f"{t}y n={e['n']:>2} med {e['median_bp']:>6} tq {e['top_quartile_bp']:>6} best {e['best_bp']:>6}"
        for t, e in b["terms"].items()))
print("  overall: " + "  ".join(f"{t}y n={e['n']} med {e['median_bp']} (UST {e['ust_pct']})"
                                for t, e in d.get("overall", {}).items()))
rows = fm.market_rows(fm.fetch_market())
for state in ("FL", "TX", ""):
    q, p = fm.parse_market(rows, state, fm.PREMIUM, fm.TERMS)
    print(f"state {state or 'any'}: {p} products -> {len(q)} carrier quotes")
