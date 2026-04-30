/**
 * Compute the running ledger balance after each entry.
 *
 * Entries arrive newest-first; we reverse to chronological order, accumulate
 * credits as positive and debits as negative, and return a Map from entry id
 * to the balance (in paise) immediately after that entry was applied.
 *
 * Note: the API returns the last 50 ledger entries, so if a merchant has more,
 * the running balance for the oldest visible entry will not include earlier
 * history. For this demo seed data (~30 entries / merchant) it is exact.
 */
export function computeRunningBalances(entries) {
  const chronological = [...entries].sort(
    (a, b) => new Date(a.created_at) - new Date(b.created_at)
  );
  const map = new Map();
  let running = 0;
  for (const e of chronological) {
    running += e.entry_type === "credit" ? e.amount_paise : -e.amount_paise;
    map.set(e.id, running);
  }
  return map;
}

export const formatInr = (paise) =>
  `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
