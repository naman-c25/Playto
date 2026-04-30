import React from "react";
import { formatDistanceToNow } from "date-fns";
import { computeRunningBalances, formatInr } from "../utils/runningBalance";

export default function LedgerTable({ entries, loading }) {
  const balances = computeRunningBalances(entries);

  if (loading && entries.length === 0) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded-xl bg-gray-100" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-gray-200 py-10 text-center">
        <p className="text-sm text-gray-400">No ledger entries yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-100">
          <thead className="bg-gray-50">
            <tr>
              {["Type", "Amount", "Balance After", "Description", "When"].map((h) => (
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
            {entries.map((e) => {
              const isCredit = e.entry_type === "credit";
              return (
                <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        isCredit
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {isCredit ? "▲ Credit" : "▼ Debit"}
                    </span>
                  </td>
                  <td
                    className={`px-4 py-3 text-sm font-bold ${
                      isCredit ? "text-emerald-600" : "text-red-500"
                    }`}
                  >
                    {isCredit ? "+" : "-"}₹{e.amount_inr}
                  </td>
                  <td className="px-4 py-3 text-sm font-semibold text-gray-700 whitespace-nowrap">
                    {balances.has(e.id) ? formatInr(balances.get(e.id)) : "—"}
                  </td>
                  <td className="max-w-xs px-4 py-3 text-sm text-gray-600 truncate">
                    {e.description}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                    {formatDistanceToNow(new Date(e.created_at), {
                      addSuffix: true,
                    })}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
