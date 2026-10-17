"""In-memory stand-in for the Supadata client. No HTTP."""

from types import SimpleNamespace

from supadata.types import Transcript


class FakeYouTube:
    def __init__(self, owner: "FakeClient") -> None:
        self._owner = owner

    @property
    def channel(self) -> "FakeYouTube":
        return self

    def videos(self, **kwargs):
        self._owner.video_calls.append(kwargs)
        if self._owner.videos_impl is not None:
            return self._owner.videos_impl(**kwargs)
        return self._owner.videos_result


class FakeClient:
    def __init__(self) -> None:
        self.video_calls: list[dict] = []
        self.transcript_calls: list[dict] = []
        self.metadata_calls: list[dict] = []
        self.videos_result = SimpleNamespace(
            video_ids=["aaaaaaaaaaa"],
            short_ids=[],
            live_ids=[],
        )
        self.videos_impl = None
        self.transcript_impl = None
        self.metadata_impl = None
        self.youtube = FakeYouTube(self)

    def transcript(self, **kwargs):
        self.transcript_calls.append(kwargs)
        if self.transcript_impl is not None:
            return self.transcript_impl(**kwargs)
        return Transcript(
            content="Hello from the test.",
            lang="en",
            available_langs=["en"],
        )

    def metadata(self, **kwargs):
        self.metadata_calls.append(kwargs)
        if self.metadata_impl is not None:
            return self.metadata_impl(**kwargs)
        return SimpleNamespace(title="Example title")
