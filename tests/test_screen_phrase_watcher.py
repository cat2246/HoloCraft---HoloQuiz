from holoquiz.screen_phrase_watcher import (
    SCREEN_PHRASE_SOURCE_TITLE_API,
    ScreenPhraseWatcher,
    ScreenPhraseCheckResult,
    ScreenReadRegion,
    TextMatchEvent,
    TitleDataClient,
)


class FakeResponse:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body.encode()


def test_title_api_uses_subtitle_as_trigger_and_title_as_result():
    def fake_urlopen(url, timeout):
        assert url == "http://127.0.0.1:8026/data/title"
        assert timeout == 2.0
        return FakeResponse('{"title":"42", "subtitle":"Good morning sir!"}')

    watcher = ScreenPhraseWatcher(
        lambda _region: "", TitleDataClient(urlopen_func=fake_urlopen)
    )
    watcher.set_source(SCREEN_PHRASE_SOURCE_TITLE_API)
    watcher.set_trigger_phrase("Good morning sir")

    event = watcher.check_once()
    assert watcher.is_ready() is True
    assert event is not None
    assert event.trigger_text == "Good morning sir!"
    assert event.result_text == "42"


def test_title_api_health_uses_health_endpoint():
    def fake_urlopen(url, timeout):
        assert url == "http://127.0.0.1:8026/health"
        return FakeResponse('{"status":"healthy"}')

    watcher = ScreenPhraseWatcher(
        lambda _region: "", TitleDataClient(urlopen_func=fake_urlopen)
    )
    assert watcher.check_api_health() == {"status": "healthy"}


def test_screen_phrase_watcher_reads_result_area_after_trigger_phrase():
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Don't eat too much cookies",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("you are now afk")

    event = watcher.check_once()

    assert event == TextMatchEvent(
        trigger_phrase="you are now afk",
        trigger_text="You are now AFK",
        result_text="Don't eat too much cookies",
    )


def test_screen_phrase_watcher_exposes_configured_regions():
    watcher = ScreenPhraseWatcher(text_reader=lambda _region: "")
    trigger_region = ScreenReadRegion(10, 20, 300, 40)
    result_region = ScreenReadRegion(30, 80, 420, 60)

    watcher.set_trigger_region(trigger_region)
    watcher.set_result_region(result_region)

    assert watcher.get_trigger_region() == trigger_region
    assert watcher.get_result_region() == result_region


def test_screen_phrase_watcher_does_not_read_result_area_without_trigger_match():
    read_regions = []

    def read_text(region):
        read_regions.append(region)
        return "No prompt here"

    watcher = ScreenPhraseWatcher(text_reader=read_text)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")

    assert watcher.check_once() is None
    assert read_regions == [ScreenReadRegion(10, 20, 300, 40)]


def test_screen_phrase_watcher_matches_trigger_when_punctuation_differs():
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "Afk again?",
        ScreenReadRegion(30, 80, 420, 60): "Still here",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("Afk, again?")

    result = watcher.check_once_detailed()

    assert result.trigger_matched is True
    assert result.event == TextMatchEvent(
        trigger_phrase="Afk, again?",
        trigger_text="Afk again?",
        result_text="Still here",
    )


def test_screen_phrase_watcher_ignores_repeated_result_until_text_changes():
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Don't eat too much cookies",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")

    assert watcher.check_once() is not None
    assert watcher.check_once() is None


def test_screen_phrase_watcher_detailed_check_reports_trigger_miss():
    watcher = ScreenPhraseWatcher(text_reader=lambda _region: "You are now AEK")
    trigger_region = ScreenReadRegion(10, 20, 300, 40)
    result_region = ScreenReadRegion(30, 80, 420, 60)
    watcher.set_trigger_region(trigger_region)
    watcher.set_result_region(result_region)
    watcher.set_trigger_phrase("You are now AFK")

    result = watcher.check_once_detailed()

    assert result == ScreenPhraseCheckResult(
        trigger_phrase="You are now AFK",
        trigger_region=trigger_region,
        result_region=result_region,
        trigger_text="You are now AEK",
        trigger_matched=False,
        result_text="",
        event=None,
        reason="trigger phrase not found",
    )


def test_screen_phrase_watcher_detailed_check_reports_repeated_result():
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Don't eat too much cookies",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")

    assert watcher.check_once_detailed().event is not None
    result = watcher.check_once_detailed()

    assert result.trigger_matched is True
    assert result.result_text == "Don't eat too much cookies"
    assert result.event is None
    assert result.reason == "result text repeated"
