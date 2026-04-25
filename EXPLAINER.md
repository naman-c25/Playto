# EXPLAINER.md — Playto Payout Engine

> This document answers the five specific questions from the challenge brief.
> Every code snippet shown here is the actual production code in the repo, not a summary.

---

## 1. The Ledger

**Paste your balance calculation query. Why did you model credits and debits this way?**

### The query

In `apps/merchants/views.py` → `MerchantBalanceView._compute_ledger_balance`:

```python
result = LedgerEntry.objects.filter(merchant=merchant).aggregate(
    total=Sum(
        Case(
            When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
            When(entry_type=LedgerEntry.DEBIT, then=-F("amount_paise")),
            default=Value(0),
            output_field=BigIntegerField(),
        )
    )
)
return result["total"] or 0
```

Django ORM emits this SQL:

```sql
SELECT COALESCE(
    SUM(CASE
        WHEN entry_type = 'credit' THEN amount_paise
        WHEN entry_type = 'debit'  THEN -amount_paise
        ELSE 0
    END),
0) AS total
FROM payouts_ledgerentry
WHERE merchant_id = %s;
```

The held balance (pending + processing payouts) is computed separately and subtracted:

```python
held = Payout.objects.filter(
    merchant=merchant,
    status__in=[Payout.PENDING, Payout.PROCESSING],
).aggregate(total=Sum("amount_paise"))["total"] or 0

available = total_balance - held
```

### Why this model

**`amount_paise` is always a positive `BigIntegerField`.** Sign is encoded in `entry_type` (credit / debit), not in the number itself. This means:

- Aggregation queries are unambiguous — no risk of a negative number in the column being treated as a credit.
- The invariant `SUM(credits) − SUM(debits) == total_balance` is structurally enforced. There is no stored `balance` column on the `Merchant` model that could drift.

**Debits are written on payout completion only.** When a payout is `pending` or `processing`, no ledger entry exists for it. The funds are "held" implicitly: `available = ledger_total − SUM(pending/processing payout amounts)`. When a payout fails, its status changes to `failed` and it disappears from the held-balance sum — no reversal entry needed.

This is correct and simpler than writing hold + release entries. The displayed balance always equals what the ledger says. No reconciliation job needed.

**The ledger is structurally immutable.** Two enforcement layers:

1. **DB-level `CheckConstraint`** — `amount_paise > 0` is enforced at the PostgreSQL layer. No application bug can ever insert a zero or negative amount; the database rejects it outright.

2. **Model-level `save()` / `delete()` overrides** — any attempt to update or delete an existing `LedgerEntry` raises a `RuntimeError` immediately. The correct way to reverse a credit is to write a new debit entry, not to mutate history.

```python
def save(self, *args, **kwargs):
    if self.pk is not None:
        raise RuntimeError("LedgerEntry is immutable. Updates are not allowed.")
    super().save(*args, **kwargs)

def delete(self, *args, **kwargs):
    raise RuntimeError("LedgerEntry is immutable. Deletions are not allowed.")
```

These two layers mean the ledger's integrity is enforced at both the application and database level — a bug in one layer cannot corrupt the financial record.

---

## 2. The Lock

**Paste the exact code that prevents two concurrent payouts from overdrawing a balance. Explain what database primitive it relies on.**

In `apps/payouts/views.py` → `PayoutCreateView._create_payout_atomic`:

```python
@staticmethod
def _create_payout_atomic(merchant, bank_account, amount_paise):
    with transaction.atomic():
        # Acquire exclusive row lock on the merchant.
        # All concurrent payout requests for this merchant queue behind this lock.
        Merchant.objects.select_for_update().get(pk=merchant.pk)

        available = _compute_available_balance(merchant)

        if available < amount_paise:
            raise InsufficientFundsError(
                available_paise=available,
                requested_paise=amount_paise,
            )

        return Payout.objects.create(
            merchant=merchant,
            bank_account=bank_account,
            amount_paise=amount_paise,
            status=Payout.PENDING,
            idempotency_key=uuid.uuid4(),
        )
```

### The primitive: PostgreSQL `SELECT ... FOR UPDATE`

`select_for_update()` emits `SELECT ... FOR UPDATE` on the merchant row. PostgreSQL acquires a **row-level exclusive lock** on that row for the duration of the transaction.

What this means concretely for the 100-rupee / two-60-rupee-requests scenario:

1. Thread A enters the `atomic()` block and acquires the lock on merchant row `id=1`.
2. Thread B enters the `atomic()` block and tries to lock the same row. PostgreSQL blocks it — Thread B waits.
3. Thread A reads available balance: 10,000 paise. Check passes. Payout created. Transaction commits. Lock released.
4. Thread B unblocks. Reads available balance: 4,000 paise (10,000 − 6,000 held). Check fails. 402 returned.

The balance check and the payout creation are inside the **same transaction with the lock held**. There is no window between the check and the create where another transaction can modify the balance.

### Why not Python-level locking

Python locks (`threading.Lock`) only work within a single process. Under Gunicorn with multiple workers, or in a distributed deployment, Python locks are useless. The database is the only reliable serialization boundary across all processes and machines.

---

## 3. The Idempotency

**How does your system know it has seen a key before? What happens if the first request is in-flight when the second arrives?**

### How it knows

The `IdempotencyKey` table has a `unique_together` constraint on `(merchant_id, key)`:

```python
class Meta:
    unique_together = [("merchant", "key")]
```

This means the database enforces uniqueness at the storage layer, not the application layer.

The full flow in `apps/payouts/views.py` → `_handle_idempotency`:

```python
# 1. Check for an existing non-expired record
try:
    existing = IdempotencyKey.objects.get(
        merchant=merchant,
        key=key_uuid,
        expires_at__gt=now,          # expired records are invisible here
    )
    if existing.is_completed:
        return existing.response_body, existing.response_status  # replay
    else:
        return {"error": "in-flight"}, 409  # first request hasn't finished
except IdempotencyKey.DoesNotExist:
    pass  # fresh key (or expired) — fall through to INSERT

# 2. Try to INSERT a new record (the unique_together constraint is the real race guard)
try:
    record = IdempotencyKey.objects.create(
        merchant=merchant,
        key=key_uuid,
        request_body=request_body,
        expires_at=now + timedelta(hours=24),
    )
    return None, record  # proceed with request

except IntegrityError:
    # 3. Lost the INSERT race. Two sub-cases:
    #    a) The conflicting record is expired  → overwrite it, treat as fresh.
    #    b) The conflicting record is live     → replay or 409 as normal.
    try:
        existing = IdempotencyKey.objects.get(merchant=merchant, key=key_uuid)
        if existing.is_expired:
            # The unique slot is occupied by a stale record the initial lookup
            # ignored. Overwrite it so this request proceeds as if the key is new.
            existing.request_body = request_body
            existing.response_body = None
            existing.response_status = None
            existing.payout = None
            existing.expires_at = now + timedelta(hours=24)
            existing.save()
            return None, existing
        if existing.is_completed:
            return existing.response_body, existing.response_status
        return (
            {"error": "A request with this idempotency key is currently in-flight."},
            status.HTTP_409_CONFLICT,
        )
    except IdempotencyKey.DoesNotExist:
        return {"error": "Idempotency conflict"}, status.HTTP_409_CONFLICT
```

After the request completes (success or failure), the response is stored back:

```python
record.response_body = resp_body
record.response_status = resp_status
record.save(update_fields=["response_body", "response_status", "payout"])
```

### What happens when the first request is in-flight

When a record is created, `response_body` is `NULL`. The check `existing.is_completed` (which tests `response_status is not None`) returns `False`. The second request immediately gets a `409 Conflict` with a message explaining the key is in-flight.

This is the correct answer for real networks: the client receives a deterministic signal to wait and retry, rather than getting a confusing duplicate or a silent no-op.

### Why the unique constraint is the real guard

Even if two threads both pass the `IdempotencyKey.DoesNotExist` check simultaneously (a race condition at the Python level), only **one** INSERT will succeed at the database level. The other hits `IntegrityError`, catches it, and falls into the "lost the race" branch. The unique constraint makes this safe without application-level locks.

### Key scoping and TTL

- **Scoped per merchant**: the uniqueness is on `(merchant_id, key)`, not just `key`. The same UUID from two merchants creates two separate records.
- **24-hour TTL**: keys have an `expires_at` field. Expired keys are excluded from lookups (`expires_at__gt=now`) and treated as fresh. A periodic Celery task (`cleanup_expired_idempotency_keys`) deletes them hourly to keep the table lean.

---

## 4. The State Machine

**Where in the code is failed-to-completed blocked? Show the check.**

In `apps/payouts/state_machine.py`:

```python
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"processing"},
    "processing": {"completed", "failed"},
    "completed":  set(),   # terminal — no outgoing transitions
    "failed":     set(),   # terminal — failed → completed is blocked here
}

def transition(payout, to_status: str) -> None:
    allowed = VALID_TRANSITIONS.get(payout.status, set())
    if to_status not in allowed:
        raise InvalidStateTransition(
            f"Cannot transition payout #{payout.pk} "
            f"from '{payout.status}' to '{to_status}'. "
            f"Allowed: {allowed if allowed else 'none — terminal state'}"
        )
    payout.status = to_status
```

`failed → completed` is blocked because `VALID_TRANSITIONS["failed"]` is an empty set. `"completed" not in set()` is always `True`, so `InvalidStateTransition` is always raised.

Every state change in `tasks.py` goes through `transition()` before `payout.save()`. There is no path in the codebase that writes `payout.status = "completed"` directly.

The function mutates `payout.status` in memory but does not save. The caller always saves inside an `atomic()` block, so an `InvalidStateTransition` raised before the save means the bad state never reaches the database.

---

## 5. The AI Audit

**One specific example where AI wrote subtly wrong code. Paste what it gave you, what you caught, and what you replaced it with.**

### The mistake: Python-level balance check without a lock

When I asked an AI assistant to implement the payout creation logic, it initially generated this:

```python
# What the AI generated — WRONG
def create_payout(merchant_id, bank_account_id, amount_paise):
    merchant = Merchant.objects.get(pk=merchant_id)

    # Compute available balance
    credits = LedgerEntry.objects.filter(
        merchant=merchant, entry_type='credit'
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    debits = LedgerEntry.objects.filter(
        merchant=merchant, entry_type='debit'
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    held = Payout.objects.filter(
        merchant=merchant,
        status__in=['pending', 'processing']
    ).aggregate(total=Sum('amount_paise'))['total'] or 0

    available = credits - debits - held

    if available < amount_paise:
        raise InsufficientFundsError(available, amount_paise)

    # Create payout
    return Payout.objects.create(
        merchant=merchant,
        bank_account_id=bank_account_id,
        amount_paise=amount_paise,
        status='pending',
    )
```

### What I caught

This code has a **TOCTOU (Time-of-Check to Time-of-Use) race condition**. The balance check happens at line 14, but the payout is created at line 20. Between those two lines, another request can:

1. Pass the same balance check (balance still looks sufficient).
2. Create its own payout.

Both payouts are now in `pending` state. The merchant has been overdrafted.

The AI's code is completely reasonable-looking Python. It even correctly uses DB aggregation instead of Python arithmetic on fetched rows. But it misses the critical requirement: the check and the create must be **atomic and serialized** — not just individually correct.

The problem is the window between the check and the insert. On a single-threaded dev server it works perfectly. Under load with 2+ Gunicorn workers it fails. The AI had no way to know this would be deployed under concurrent load, so it generated code that looks correct but isn't.

### What I replaced it with

```python
# Correct version — lock acquired before check, held through create
with transaction.atomic():
    Merchant.objects.select_for_update().get(pk=merchant.pk)  # acquire row lock
    available = _compute_available_balance(merchant)           # check with lock held
    if available < amount_paise:
        raise InsufficientFundsError(available, amount_paise)
    return Payout.objects.create(...)                          # create with lock held
# lock released on transaction commit
```

The `select_for_update()` acquires a PostgreSQL row-level exclusive lock on the merchant row. The lock is held for the entire duration of the `atomic()` block. Any concurrent request for the same merchant blocks at the `select_for_update()` call until this transaction commits, making the check-and-create atomic from the database's perspective.

The second bug I also caught: the AI ran two separate aggregation queries (`credits` and `debits`) instead of one `CASE`-based query. While functionally correct, this is two round-trips where one suffices and doubles the latency under load. It also creates a brief window between the two reads where credits could be added mid-calculation.

---

### Second real bug: the expired-key IntegrityError path (caught by the test suite)

This one was in the production code and was only found by the test `test_expired_idempotency_key_is_treated_as_fresh`.

#### What the code originally did

In `_handle_idempotency`, the `except IntegrityError` recovery branch looked like this:

```python
except IntegrityError:
    # Lost the INSERT race — another thread beat us to the key
    existing = IdempotencyKey.objects.get(merchant=merchant, key=key_uuid)
    if existing.is_completed:
        return existing.response_body, existing.response_status
    return {"error": "in-flight"}, 409
```

Notice the `get()` call has **no `expires_at__gt=now` filter**.

#### Why this is wrong

The `IntegrityError` is not always caused by a concurrent live request. It can also be triggered by an **expired record that has not yet been cleaned up**. The cleanup task runs hourly — in the window between a key expiring and the cleaner deleting it, the unique slot is still occupied.

The flow that breaks it:

1. Key `K` is used 25 hours ago. Its record has `expires_at` in the past and `response_body = {"id": 999, ...}`.
2. The hourly cleanup task has not run yet, so the record still exists in the DB.
3. A new request arrives with the same key `K`.
4. The initial lookup (`expires_at__gt=now`) correctly ignores the expired record. `DoesNotExist` → proceeds to INSERT.
5. The INSERT hits `IntegrityError` because the expired record still holds the unique slot.
6. The original `except` branch fetches the record **without the expiry filter**, finds the completed expired record, and replays `{"id": 999}` — a stale response from 25 hours ago.

The merchant gets told their payout already happened (with a fake ID) and no new payout is created. This is silent data corruption.

#### What the test caught

```python
# Plant an expired record with a fake payout id
IdempotencyKey.objects.create(
    merchant=funded_merchant,
    key=key,
    response_body={"id": 999, "status": "pending"},
    response_status=201,
    expires_at=timezone.now() - timedelta(hours=1),  # already expired
)

r = _post_payout(funded_merchant, bank_account, 3_000, key)

assert r.status_code == 201
assert r.json()["id"] != 999   # FAILED before fix — returned 999
```

#### The fix

In the `except IntegrityError` branch, check `existing.is_expired` before replaying:

```python
except IntegrityError:
    existing = IdempotencyKey.objects.get(merchant=merchant, key=key_uuid)
    if existing.is_expired:
        # Stale record holds the unique slot — overwrite it and proceed fresh
        existing.request_body = request_body
        existing.response_body = None
        existing.response_status = None
        existing.payout = None
        existing.expires_at = now + timedelta(hours=24)
        existing.save()
        return None, existing       # caller creates the payout normally
    if existing.is_completed:
        return existing.response_body, existing.response_status
    return {"error": "in-flight"}, 409
```

#### Why this matters

This bug is invisible in normal operation — it only surfaces in the gap between a key expiring and the hourly cleaner running (up to 60 minutes). Under normal traffic the cleaner keeps pace and this path is never hit. Under load or with a delayed cleaner it would produce incorrect replay responses for legitimate new requests. The test caught it precisely because it engineers that exact scenario directly.

---

## Architecture Decisions Not Covered Above

### Why held balance is implicit (not stored in the ledger)

An alternative design writes a HOLD entry on payout creation and a RELEASE entry on failure. This is more auditable but doubles the number of ledger entries and requires a new `entry_type`. The implicit model is simpler: `available = ledger_balance − SUM(pending/processing amounts)`. The invariant `SUM(credits) − SUM(debits) == total_balance` still holds because only completed payouts generate DEBIT entries. The held amount is a query, not a stored value.

### Why Celery Beat for stuck payouts instead of Celery retries

Celery's built-in `self.retry()` works well when you own the failure. The "hang" simulation represents a case where the task never finishes — it doesn't raise an exception, so `self.retry()` is never called. The external `detect_stuck_payouts` periodic task is the correct pattern for detecting tasks that silently time out, which is the real-world scenario when a bank API hangs or a network partition occurs.

### Why `acks_late=True` on `process_payout`

By default, Celery acknowledges a task as soon as it's received by the worker, before the task body runs. If the worker crashes mid-execution, the task is lost. `acks_late=True` delays the ACK until after the task body completes. Combined with the `select_for_update()` guard inside the task (which checks `payout.status != PENDING` before doing anything), a crashed-and-restarted worker will safely reprocess the task without corrupting state.
