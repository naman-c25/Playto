import React from "react";
import { formatDistanceToNow } from "date-fns";

const STATUS_STYLES = {
  pending:    "bg-amber-100 text-amber-800",
  processing: "bg-blue-100 text-blue-800",
  completed:  "bg-emerald-100 text-emerald-800",
  failed:     "bg-red-100 text-red-800",
};

const STATUS_DOTS = {
  pending:    "bg-amber-400",
  processing: "bg-blue-400 animate-pulse",
  completed:  "bg-emerald-400",
  failed:     "bg-red-400",
};

function StatusBadge({ status }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700"}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOTS[status] ?? "bg-gray-400"}`} />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export default function PayoutTable({ payouts, loading }) {
  if (loading && payouts.length === 0) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-xl bg-gray-100" />
        ))}
      </div>
    );
  }

  if (payouts.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-gray-200 py-12 text-center">
        <p className="text-sm text-gray-400">No payouts yet. Request one above.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-100">
          <thead className="bg-gray-50">
            <tr>
              {["ID", "Amount", "Status", "Bank", "Attempts", "Created"].map((h) => (
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
            {payouts.map((p) => (
              <tr key={p.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 text-sm font-mono text-gray-500">#{p.id}</td>
                <td className="px-4 py-3 text-sm font-semibold text-gray-900">
                  ₹{p.amount_inr}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={p.status} />
                  {p.failure_reason && (
                    <p className="mt-1 max-w-xs truncate text-xs text-red-500">
                      {p.failure_reason}
                    </p>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">
                  <div>{p.bank_account?.bank_name}</div>
                  <div className="font-mono">{p.bank_account?.ifsc_code}</div>
                </td>
                <td className="px-4 py-3 text-center text-sm text-gray-600">
                  {p.attempt_count}
                </td>
                <td className="px-4 py-3 text-xs text-gray-400">
                  {formatDistanceToNow(new Date(p.created_at), { addSuffix: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
