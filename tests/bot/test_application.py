"""Long-polling offset and error-isolation tests."""

from course_platform.bot.application import BotApplication
from course_platform.bot.types import TelegramUpdate


class FakeAPI:
    def __init__(self, updates: list[TelegramUpdate]) -> None:
        self.updates = updates
        self.offsets: list[int | None] = []

    async def get_updates(
        self,
        *,
        offset: int | None,
        poll_timeout: int,
    ) -> list[TelegramUpdate]:
        self.offsets.append(offset)
        updates, self.updates = self.updates, []
        return updates


class FakeRouter:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.handled: list[int] = []
        self.fail_on = fail_on

    async def handle(self, update: TelegramUpdate) -> bool:
        self.handled.append(update.update_id)
        if update.update_id == self.fail_on:
            raise RuntimeError("handler failed")
        return True


def update(update_id: int) -> TelegramUpdate:
    return TelegramUpdate(update_id=update_id)


async def test_poll_once_advances_offset() -> None:
    api = FakeAPI([update(10), update(11)])
    router = FakeRouter()
    application = BotApplication(api, router, poll_timeout=1)  # type: ignore[arg-type]

    assert await application.poll_once() == 2
    assert await application.poll_once() == 0

    assert api.offsets == [None, 12]
    assert router.handled == [10, 11]


async def test_handler_failure_does_not_block_next_update(caplog) -> None:
    api = FakeAPI([update(20), update(21)])
    router = FakeRouter(fail_on=20)
    application = BotApplication(api, router, poll_timeout=1)  # type: ignore[arg-type]

    assert await application.poll_once() == 2

    assert router.handled == [20, 21]
    assert "Failed to handle Telegram update 20" in caplog.text
