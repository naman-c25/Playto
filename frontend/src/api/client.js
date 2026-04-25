/**
 * API client for the Playto Payout Engine backend.
 *
 * All amounts are in paise (integers) at the API boundary.
 * INR formatting is done client-side from the `*_inr` string fields.
 */
import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";

const http = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// ---------------------------------------------------------------------------
// Merchants
// ---------------------------------------------------------------------------

export const getMerchants = () =>
  http.get("/merchants/").then((r) => r.data);

export const getMerchantBalance = (merchantId) =>
  http.get(`/merchants/${merchantId}/balance/`).then((r) => r.data);

export const getMerchantLedger = (merchantId) =>
  http.get(`/merchants/${merchantId}/ledger/`).then((r) => r.data);

// ---------------------------------------------------------------------------
// Payouts
// ---------------------------------------------------------------------------

export const getMerchantPayouts = (merchantId) =>
  http.get(`/merchants/${merchantId}/payouts/`).then((r) => r.data);

export const getPayout = (payoutId) =>
  http.get(`/payouts/${payoutId}/`).then((r) => r.data);

/**
 * Request a payout.
 *
 * The client generates the idempotency key and is responsible for reusing
 * the SAME key on retries. This ensures network failures don't create
 * duplicate payouts.
 *
 * @param {string} merchantId
 * @param {number} amountPaise  - integer, never float
 * @param {number} bankAccountId
 * @param {string} idempotencyKey - UUID v4, caller-generated
 */
export const createPayout = (merchantId, amountPaise, bankAccountId, idempotencyKey) =>
  http.post(
    "/payouts/",
    { amount_paise: amountPaise, bank_account_id: bankAccountId },
    {
      headers: {
        "X-Merchant-ID": String(merchantId),
        "Idempotency-Key": idempotencyKey,
      },
    }
  ).then((r) => r.data);
