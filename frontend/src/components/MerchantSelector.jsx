import React from "react";

export default function MerchantSelector({ merchants, selected, onChange }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-sm font-medium text-gray-600 whitespace-nowrap">
        Viewing as:
      </label>
      <select
        value={selected?.id ?? ""}
        onChange={(e) => {
          const m = merchants.find((m) => m.id === Number(e.target.value));
          if (m) onChange(m);
        }}
        className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      >
        {merchants.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}
