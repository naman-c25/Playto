import React from "react";

function Card({ label, inr, paise, color, icon }) {
  return (
    <div className={`rounded-2xl border bg-white p-6 shadow-sm ${color}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            {label}
          </p>
          <p className="mt-2 text-3xl font-bold text-gray-900">₹{inr}</p>
          <p className="mt-1 text-xs text-gray-400">{paise.toLocaleString()} paise</p>
        </div>
        <span className="text-2xl">{icon}</span>
      </div>
    </div>
  );
}

export default function BalanceCards({ balance }) {
  if (!balance) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-gray-100" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Card
        label="Available Balance"
        inr={balance.available_balance_inr}
        paise={balance.available_balance_paise}
        color="border-emerald-100"
        icon="💰"
      />
      <Card
        label="Held Balance"
        inr={balance.held_balance_inr}
        paise={balance.held_balance_paise}
        color="border-amber-100"
        icon="⏳"
      />
      <Card
        label="Total Earned"
        inr={balance.total_earned_inr}
        paise={balance.total_earned_paise}
        color="border-blue-100"
        icon="📈"
      />
    </div>
  );
}
