class PayoutEngineError(Exception):
    """Base for all payout engine domain errors."""


class InvalidStateTransition(PayoutEngineError):
    """
    Raised when code attempts an illegal payout state transition.
    E.g. completed → pending, failed → completed.
    """


class InsufficientFundsError(PayoutEngineError):
    """
    Raised when the merchant's available balance is less than the
    requested payout amount at the moment the lock is held.
    """

    def __init__(self, available_paise: int, requested_paise: int) -> None:
        self.available_paise = available_paise
        self.requested_paise = requested_paise
        super().__init__(
            f"Insufficient funds: requested {requested_paise} paise, "
            f"available {available_paise} paise"
        )
