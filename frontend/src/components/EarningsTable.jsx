import React from "react";
import { formatDistanceToNow, format } from "date-fns";
import { computeRunningBalances, formatInr } from "../utils/runningBalance";

const SOURCE_ICONS = {
  "Client payment": "🧾",
  "Retainer fee": "📅",
  "Project milestone": "🎯",
  default: "💵",
};

function parseDescription(description) {
  for (const prefix of Object.keys(SOURCE_ICONS)) {
    if (description.startsWith(prefix)) {
      const detail = description.slice(prefix.length).replace(/^[\s—–-]+/, "");
      return { label: prefix, detail, icon: SOURCE_ICONS[prefix] };
    }
  }
  return { label: description, detail: null, icon: SOURCE_ICONS.default };
}

function ConversionBadge({ usdAmount, exchangeRate, amountInr }) {
  if (!usdAmount || !exchangeRate) {
    return <span className="text-sm font-bold text-emerald-600">+₹{amountInr}</span>;
  }
  return (
    <div>
      {/* Original USD amount */}
      <div className="flex items-center gap-1.5">
        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-semibold text-blue-700 border border-blue-100">
          ${usdAmount} USD
        </span>
        <span className="text-gray-300 text-xs">→</span>
        <span className="text-sm font-bold text-emerald-600">+₹{amountInr}</span>
      </div>
      {/* Exchange rate used */}
      <div className="mt-0.5 text-xs text-gray-400">
        at ₹{exchangeRate}/$ (rate at settlement)
      </div>
    </div>
  );
}

export default function EarningsTable({ entries, loading }) {
  const credits = entries.filter((e) => e.entry_type === "credit");
  // Running balance is computed across the full ledger (incl. debits) so that
  // a credit's "balance after" reflects payouts that happened between credits.
  const balances = computeRunningBalances(entries);


  const totalPaise = credits.reduce((sum, e) => sum + e.amount_paise, 0);
  const totalInr = (totalPaise / 100).toFixed(2);

  const totalUsdCents = credits.reduce((sum, e) => sum + (e.usd_cents ?? 0), 0);
  const totalUsd = totalUsdCents > 0 ? (totalUsdCents / 100).toFixed(2) : null;

  if (loading && credits.length === 0) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-xl bg-gray-100" />
        ))}
      </div>
    );
  }

  if (credits.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-gray-200 py-10 text-center">
        <p className="text-sm text-gray-400">No incoming payments yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Summary strip */}
      <div className="flex items-center justify-between rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-600">
            Total Received — {credits.length} payments
          </p>
          <div className="mt-1 flex items-center gap-3">
            <p className="text-2xl font-bold text-emerald-700">₹{totalInr}</p>
            {totalUsd && (
              <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                ${totalUsd} USD received
              </span>
            )}
          </div>
        </div>
        <span className="text-2xl">💰</span>
      </div>

      {/* FX info banner */}
      {totalUsd && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <span className="text-base">🔄</span>
          <span>
            Customer payments arrive in <strong>USD</strong>. The rate at the time of each
            payment is locked in and shown below — your INR credit reflects the exact
            conversion that was applied.
          </span>
        </div>
      )}

      {/* Payments table */}
      <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                {["Source", "Reference", "Amount (USD → INR)", "Balance After", "Received"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 bg-white">
              {credits.map((e) => {
                const { label, detail, icon } = parseDescription(e.description);
                return (
                  <tr key={e.id} className="transition-colors hover:bg-emerald-50/40">
                    {/* Source type */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{icon}</span>
                        <span className="text-sm font-medium text-gray-800">{label}</span>
                      </div>
                    </td>

                    {/* Reference / detail from description */}
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {detail ?? <span className="text-gray-300">—</span>}
                    </td>

                    {/* USD → INR conversion */}
                    <td className="px-4 py-3">
                      <ConversionBadge
                        usdAmount={e.usd_amount}
                        exchangeRate={e.exchange_rate_display}
                        amountInr={e.amount_inr}
                      />
                    </td>

                    {/* Running balance after this credit was applied */}
                    <td className="px-4 py-3 text-sm font-semibold text-gray-700 whitespace-nowrap">
                      {balances.has(e.id) ? formatInr(balances.get(e.id)) : "—"}
                    </td>

                    {/* Date */}
                    <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                      <div>
                        {formatDistanceToNow(new Date(e.created_at), { addSuffix: true })}
                      </div>
                      <div className="mt-0.5 font-mono text-gray-300">
                        {format(new Date(e.created_at), "dd MMM yyyy")}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
