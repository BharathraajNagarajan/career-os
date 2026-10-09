from collections.abc import Callable

from app.actions.jobs import WakeActionPayload
from app.actions.service import ActionService
from app.core.logging import get_logger
from app.db.tenancy import NotFound
from app.jobs.registry import JobContext

log = get_logger(__name__)


def make_wake_action_handler() -> Callable[[JobContext, WakeActionPayload], None]:
    def handle(context: JobContext, payload: WakeActionPayload) -> None:
        user_id = context.require_user_id()
        try:
            woken = ActionService(context.session).wake_if_current(
                user_id=user_id, action_id=payload.action_id, state_version=payload.state_version
            )
        except NotFound:
            woken = False
        log.info("wake_action_handled", action_id=str(payload.action_id), woken=woken)

    return handle
