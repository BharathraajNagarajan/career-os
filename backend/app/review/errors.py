class ReviewError(Exception):
    code = "review_error"


class InvalidTransition(ReviewError):
    code = "invalid_transition"


class NoHandler(ReviewError):
    code = "no_handler"


class InvalidPayload(ReviewError):
    code = "invalid_payload"
