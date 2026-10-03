class TransitionError(Exception):
    code = "invalid_transition"
    status_code = 409

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class InvalidTransition(TransitionError):
    code = "invalid_transition"


class EventTypeNotAllowed(TransitionError):
    code = "event_type_not_allowed"
    status_code = 422


class ActorNotAllowed(TransitionError):
    code = "actor_not_allowed"


class TerminalBeforeReopen(TransitionError):
    code = "terminal_before_reopen"


class CannotVoid(TransitionError):
    code = "cannot_void"


class AlreadyVoided(TransitionError):
    code = "already_voided"


class NotTerminal(TransitionError):
    code = "not_terminal"


class SnoozeNotInFuture(TransitionError):
    code = "snooze_not_in_future"
    status_code = 422
