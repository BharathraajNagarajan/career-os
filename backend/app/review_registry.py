from app.evidence.review_handlers import register_evidence_handlers
from app.review.handlers import ReviewHandlerRegistry


def build_review_registry() -> ReviewHandlerRegistry:
    registry = ReviewHandlerRegistry()
    register_evidence_handlers(registry)
    return registry
