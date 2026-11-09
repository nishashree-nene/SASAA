"""Quick engine unit tests — run from backend/"""
import sys, os
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app.verification.verification_engine import run_verification
from app.verification.time_detector import detect_times

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []

def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"  {PASS if ok else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, ok))

print("=== Verification Engine Unit Tests ===\n")

# ── Test 1: Tamil spec transcript ────────────────────────────────────────────
print("[T1] Tamil spec transcript")
tamil = (
    '\u0b9f\u0bcd\u0bb0\u0bbe\u0ba9\u0bcd\u0bb8\u0bcd\u0b83\u0baa\u0bb0\u0bcd '
    '\u0b83\u0baa\u0bbf\u0b83\u0baa\u0bcd\u0b9f\u0bbf \u0bb0\u0bc2\u0baa\u0bc0\u0bb8\u0bcd, '
    '\u0ba8\u0bbe\u0b9f\u0bcd '
    '\u0b83\u0baa\u0bbf\u0b83\u0baa\u0bcd\u0b9f\u0bc0\u0ba9\u0bcd \u0bb0\u0bc2\u0baa\u0bc0\u0bb8\u0bcd. '
    '\u0b90 \u0bb9\u0bc7\u0bb5\u0bcd \u0b83\u0baa\u0bcb\u0bb0\u0bcd \u0b9a\u0bbe\u0b95\u0bcd\u0bb2\u0bc7\u0b9f\u0bcd\u0bb8\u0bcd.'
)
entities, summary = run_verification(tamil)
check("entities found > 0", summary.total_entities > 0, f"got {summary.total_entities}")
check("negation detected", summary.has_negation)
check("financial detected", summary.has_financial)
check("message_needs_verification", summary.message_needs_verification)
print(f"  [INFO] Entities: {summary.total_entities}, flagged={summary.flagged_count}, needs_review={summary.needs_review_count}")
for e in entities:
    print(f"    [{e.entity_type.value}] norm={e.normalized_value!r} status={e.verification_status.value} risk={e.risk_level.value}")

# ── Test 2: English equivalent ───────────────────────────────────────────────
print("\n[T2] English equivalent")
english = "Transfer fifty rupees, not fifteen rupees. I have four chocolates."
e2, s2 = run_verification(english)
check("entities found", s2.total_entities > 0, str(s2.total_entities))
check("negation found", s2.has_negation)
check("financial found", s2.has_financial)
types = {e.entity_type.value for e in e2}
check("NEGATION type present", "NEGATION" in types, str(types))
check("AMOUNT type present", "AMOUNT" in types, str(types))
for e in e2:
    print(f"    [{e.entity_type.value}] raw={ascii(e.raw_value)} norm={e.normalized_value!r} status={e.verification_status.value}")

# ── Test 3: Two amounts + negation relationship ───────────────────────────────
print("\n[T3] Fifty vs fifteen relationship")
amounts = [e for e in e2 if e.entity_type.value == "AMOUNT"]
check("two amounts found", len(amounts) >= 2, f"got {len(amounts)}")
if len(amounts) >= 2:
    vals = sorted([e.normalized_value for e in amounts if e.normalized_value])
    check("50 and 15 both detected", "15" in vals and "50" in vals, str(vals))
    # Both should be flagged for review, not automatically called an error
    all_needs_review = all(
        e.verification_status.value in ("NEEDS_REVIEW","FLAGGED")
        for e in amounts
    )
    check("amounts marked NEEDS_REVIEW (not auto-corrected)", all_needs_review)

# ── Test 4: AM/PM guardian.py rule ───────────────────────────────────────────
print("\n[T4] AM/PM ambiguity rule (guardian.py)")
t1 = detect_times("Call me at 5.")
check("ambiguous time flagged", t1 and t1[-1].is_ambiguous)
check("meridiem is None (not guessed)", t1 and t1[-1].meridiem is None)
t2 = detect_times("Call me at 5 PM.")
check("explicit PM extracted correctly", any(t.meridiem == "PM" and not t.is_ambiguous for t in t2))

# ── Test 5: Empty transcript ──────────────────────────────────────────────────
print("\n[T5] Edge cases")
e_empty, s_empty = run_verification("")
check("empty transcript returns 0 entities", s_empty.total_entities == 0)
e_space, s_space = run_verification("   ")
check("whitespace transcript returns 0 entities", s_space.total_entities == 0)

# ── Test 6: run_in_executor compatibility ─────────────────────────────────────
print("\n[T6] async run_in_executor compatibility")
import asyncio
async def _test():
    loop = asyncio.get_event_loop()
    e, s = await loop.run_in_executor(None, run_verification, english)
    return s.total_entities
count = asyncio.run(_test())
check("run_in_executor works", count > 0, f"{count} entities")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 50)
passed = sum(1 for _, p in results if p)
failed = sum(1 for _, p in results if not p)
print(f"Results: {passed}/{len(results)} passed | {failed} failed")
if failed:
    print("\nFailed:")
    for name, ok in results:
        if not ok:
            print(f"  x {name}")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)
