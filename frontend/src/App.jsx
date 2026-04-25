/**
 * Main application — single-page merchant dashboard.
 *
 * Data flow:
 *   - Merchants list fetched once on mount.
 *   - Selected merchant's balance, payouts, and ledger polled every 5s.
 *   - PayoutForm triggers an immediate refresh after a successful submission.
 *
 * Live updates via polling (no WebSocket) — appropriate for this domain
 * where sub-second latency is not required.
 */
import React, { useState, useEffect, useCallback } from "react";
import {
  getMerchants,
  getMerchantBalance,
  getMerchantLedger,
  getMerchantPayouts,
} from "./api/client";
import { usePolling } from "./hooks/usePolling";
import MerchantSelector from "./components/MerchantSelector";
import BalanceCards from "./components/BalanceCards";
import PayoutForm from "./components/PayoutForm";
import PayoutTable from "./components/PayoutTable";
import LedgerTable from "./components/LedgerTable";
import EarningsTable from "./components/EarningsTable";

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedMerchant, setSelectedMerchant] = useState(null);
  const [balance, setBalance] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [loadingData, setLoadingData] = useState(true);
  const [activeTab, setActiveTab] = useState("payouts");
  const [lastUpdated, setLastUpdated] = useState(null);

  // Fetch merchant list once on mount
  useEffect(() => {
    getMerchants().then((data) => {
      setMerchants(data);
      if (data.length > 0) setSelectedMerchant(data[0]);
    });
  }, []);

  // Poll merchant data every 5 seconds — keeps payout status live
  const fetchData = useCallback(async () => {
    if (!selectedMerchant) return;
    try {
      const [bal, pays, led] = await Promise.all([
        getMerchantBalance(selectedMerchant.id),
        getMerchantPayouts(selectedMerchant.id),
        getMerchantLedger(selectedMerchant.id),
      ]);
      setBalance(bal);
      setPayouts(pays);
      setLedger(led);
      setLastUpdated(new Date());
    } finally {
      setLoadingData(false);
    }
  }, [selectedMerchant]);

  usePolling(fetchData, 5000, Boolean(selectedMerchant));

  // Reset when merchant switches
  useEffect(() => {
    setBalance(null);
    setPayouts([]);
    setLedger([]);
    setLoadingData(true);
  }, [selectedMerchant]);

  const hasActivePayouts = payouts.some(
    (p) => p.status === "pending" || p.status === "processing"
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-100 bg-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white font-bold text-sm">
              P
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-900">Playto Pay</h1>
              <p className="text-xs text-gray-400">Payout Engine</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {lastUpdated && (
              <p className="hidden text-xs text-gray-400 sm:block">
                {hasActivePayouts && (
                  <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400 align-middle" />
                )}
                Updated {lastUpdated.toLocaleTimeString()}
              </p>
            )}
            {merchants.length > 0 && selectedMerchant && (
              <MerchantSelector
                merchants={merchants}
                selected={selectedMerchant}
                onChange={(m) => {
                  setSelectedMerchant(m);
                }}
              />
            )}
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {!selectedMerchant ? (
          <div className="py-24 text-center text-gray-400">Loading merchants…</div>
        ) : (
          <div className="space-y-8">
            {/* Balance cards */}
            <section>
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-500">
                Balance
              </h2>
              <BalanceCards balance={balance} />
            </section>

            {/* Two-column: payout form + history */}
            <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
              {/* Payout request form — left column */}
              <div className="lg:col-span-1">
                <PayoutForm
                  key={selectedMerchant.id}
                  merchant={selectedMerchant}
                  onSuccess={fetchData}
                />
              </div>

              {/* History — right column */}
              <div className="lg:col-span-2">
                {/* Tabs */}
                <div className="mb-4 flex items-center gap-1 rounded-xl border border-gray-100 bg-white p-1 shadow-sm w-fit">
                  {[
                    { id: "payouts", label: "Payout History" },
                    { id: "earnings", label: "Earnings" },
                    { id: "ledger", label: "Full Ledger" },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
                        activeTab === tab.id
                          ? "bg-brand-600 text-white shadow-sm"
                          : "text-gray-500 hover:text-gray-800"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {activeTab === "payouts" && (
                  <PayoutTable payouts={payouts} loading={loadingData} />
                )}
                {activeTab === "earnings" && (
                  <EarningsTable entries={ledger} loading={loadingData} />
                )}
                {activeTab === "ledger" && (
                  <LedgerTable entries={ledger} loading={loadingData} />
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
