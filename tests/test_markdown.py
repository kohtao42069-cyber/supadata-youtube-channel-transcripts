import yaml

from channel_transcripts.markdown import render_markdown, yaml_scalar


def test_front_matter_order_and_plain_body():
    text = render_markdown(
        video_id="abcdefghijk",
        title=None,
        url="https://www.youtube.com/watch?v=abcdefghijk",
        channel="@ExampleChannel",
        lang="en",
        fetched_at="2026-10-17T13:00:00Z",
        body="  First line.\n\nSecond line.  ",
    )
    assert text == (
        "---\n"
        "video_id: abcdefghijk\n"
        "url: https://www.youtube.com/watch?v=abcdefghijk\n"
        'channel: "@ExampleChannel"\n'
        "lang: en\n"
        "fetched_at: 2026-10-17T13:00:00Z\n"
        "source: supadata\n"
        "---\n"
        "\n"
        "First line.\n"
        "\n"
        "Second line.\n"
    )


def test_title_is_included_only_when_present_and_quoted_when_needed():
    text = render_markdown(
        video_id="abcdefghijk",
        title='Say "hello": world',
        url="https://www.youtube.com/watch?v=abcdefghijk",
        channel="@ExampleChannel",
        lang="en",
        fetched_at="2026-10-17T13:00:00Z",
        body="Body",
    )
    assert 'title: "Say \\"hello\\": world"\n' in text
    assert text.splitlines()[1] == "video_id: abcdefghijk"
    assert text.splitlines()[2].startswith("title:")
    assert text.splitlines()[3].startswith("url:")


def test_yaml_scalar_quotes_reserved_words():
    assert yaml_scalar("yes") == '"yes"'
    assert yaml_scalar("") == '""'
    assert yaml_scalar("@jawed") == '"@jawed"'
    assert yaml_scalar("-x") == '"-x"'
    assert yaml_scalar("a: b") == '"a: b"'
    assert yaml_scalar("x #y") == '"x #y"'


def test_front_matter_parses_with_pyyaml():
    for channel in ("@jawed", "-x", "a: b", "x #y"):
        text = render_markdown(
            video_id="abcdefghijk",
            title=None,
            url="https://www.youtube.com/watch?v=abcdefghijk",
            channel=channel,
            lang="en",
            fetched_at="2026-10-17T13:00:00Z",
            body="Hello",
        )
        front = text.split("---", 2)[1]
        loaded = yaml.safe_load(front)
        assert loaded["channel"] == channel
        assert loaded["video_id"] == "abcdefghijk"
        assert loaded["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
        assert loaded["source"] == "supadata"
