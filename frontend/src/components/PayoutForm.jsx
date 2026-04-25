/**
 * PayoutForm — lets the merchant request a payout.
 *
 * The idempotency key is generated here and stored in component state.
 * If the user submits and gets a network error, they can retry with the
 * same key by clicking the button again — the backend deduplicates it.
 * A new key is generated only after a successful submission.
 */
import React, { useState, useEffect, useCallback } from "react";
import { createPayout } from "../api/client";

function generateKey() {
  return crypto.randomUUID();
}

export default function PayoutForm({ merchant, onSuccess }) {
  const [amountInr, setAmountInr] = useState("");
  const [bankAccountId, setBankAccountId] = useState(
    merchant?.bank_accounts?.[0]?.id ?? ""
  );
  const [currentKey, setCurrentKey] = useState(generateKey);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const accounts = merchant?.bank_accounts ?? [];

  // Reset form state whenever the selected merchant changes
  useEffect(() => {
    setBankAccountId(merchant?.bank_accounts?.[0]?.id ?? "");
    setAmountInr("");
    setError(null);
    setSuccess(null);
    setCurrentKey(generateKey());
  }, [merchant?.id]);

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      setError(null);
      setSuccess(null);

      const inrFloat = parseFloat(amountInr);
      if (isNaN(inrFloat) || inrFloat <= 0) {
        setError("Enter a valid amount greater than ₹0.");
        return;
      }

      // Convert INR to paise — integer arithmetic, no float storage
      const amountPaise = Math.round(inrFloat * 100);

      if (amountPaise < 100) {
        setError("Minimum payout is ₹1 (100 paise).");
        return;
      }

      setLoading(true);
      try {
        const payout = await createPayout(
          merchant.id,
          amountPaise,
          bankAccountId,
          currentKey
        );
        setSuccess(`Payout #${payout.id} queued for ₹${payout.amount_inr}`);
        setAmountInr("");
        // Generate a fresh key for the next request
        setCurrentKey(generateKey());
        onSuccess?.();
      } catch (err) {
        const data = err.response?.data;
        if (err.response?.status === 402) {
          setError(
            `Insufficient funds. Available: ₹${data.available_inr ?? "—"}`
          );
        } else if (err.response?.status === 409) {
          setError("This request is already being processed. Please wait.");
        } else {
          setError(data?.error ?? "Something went wrong. Please try again.");
        }
      } finally {
        setLoading(false);
      }
    },
    [amountInr, bankAccountId, currentKey, merchant]
  );

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <h2 className="mb-5 text-lg font-semibold text-gray-800">
        Request Payout
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Amount */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Amount (₹)
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-3 flex items-center text-gray-400 font-medium">
              ₹
            </span>
            <input
              type="number"
              min="1"
              step="0.01"
              value={amountInr}
              onChange={(e) => setAmountInr(e.target.value)}
              placeholder="0.00"
              required
              className="w-full rounded-lg border border-gray-200 py-2 pl-7 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            />
          </div>
        </div>

        {/* Bank account selector */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Destination Account
          </label>
          {accounts.length === 0 ? (
            <p className="text-sm text-gray-400">No bank accounts on file.</p>
          ) : (
            <select
              value={bankAccountId}
              onChange={(e) => setBankAccountId(Number(e.target.value))}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            >
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.bank_name} — {acc.ifsc_code} ({acc.account_holder_name})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Feedback */}
        {error && (
          <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </p>
        )}
        {success && (
          <p className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {success}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || accounts.length === 0}
          className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Submitting…" : "Request Payout"}
        </button>

        <p className="text-center text-xs text-gray-400">
          Key: <span className="font-mono">{currentKey.slice(0, 8)}…</span>
          {" "}(reused on retry)
        </p>
      </form>
    </div>
  );
}
