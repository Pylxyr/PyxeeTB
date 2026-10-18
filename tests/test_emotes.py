import asyncio

from conftest import run
from pyxeetb.config import _emote_providers_env
from pyxeetb.emotes import (
    PROVIDERS,
    EmoteService,
    ThirdPartyEmote,
    parse_7tv_set,
    parse_bttv,
    parse_ffz_sets,
    safe_image_url,
)


def _7tv_entry(name, emote_id, *, listed=True, flags=0, data_flags=0, files=("1x.webp", "2x.webp")):
    return {
        "id": emote_id,
        "name": name,
        "flags": flags,
        "data": {
            "id": emote_id,
            "listed": listed,
            "flags": data_flags,
            "host": {"url": f"//cdn.7tv.app/emote/{emote_id}", "files": [{"name": f} for f in files]},
        },
    }


def test_7tv_includes_unlisted_emotes_from_the_active_set():
    out = parse_7tv_set({"emotes": [_7tv_entry("Listed", "AAA"), _7tv_entry("Hidden", "BBB", listed=False)]})
    assert [e.name for e in out] == ["Listed", "Hidden"]
    assert out[1].url == "https://cdn.7tv.app/emote/BBB/2x.webp"


def test_7tv_skips_emotes_flagged_not_allowed_on_twitch():
    out = parse_7tv_set({"emotes": [_7tv_entry("Banned", "CCC", data_flags=1 << 24), _7tv_entry("Ok", "DDD")]})
    assert [e.name for e in out] == ["Ok"]


def test_7tv_zero_width_from_set_or_emote_flags_and_alias_name():
    out = parse_7tv_set({"emotes": [_7tv_entry("Hat", "EEE", flags=1), _7tv_entry("Fx", "FFF", data_flags=1 << 8),
                                     _7tv_entry("Plain", "GGG")]})
    assert [(e.name, e.zero_width) for e in out] == [("Hat", True), ("Fx", True), ("Plain", False)]


def test_7tv_garbage_is_skipped_not_raised():
    assert parse_7tv_set(None) == [] and parse_7tv_set({"emotes": "x"}) == []
    assert parse_7tv_set({"emotes": [None, 3, {"name": "no id"}, _7tv_entry("bad id", "../x")]}) == []


def test_bttv_channel_and_modifier_handling():
    out = parse_bttv([{"id": "54fa925e01e468494b85b54d", "code": "OMEGALUL"},
                      {"id": "54fa925e01e468494b85b54e", "code": "cvHazmat", "modifier": True}])
    assert [e.name for e in out] == ["OMEGALUL"]
    assert out[0].url == "https://cdn.betterttv.net/emote/54fa925e01e468494b85b54d/2x.webp"


def test_ffz_global_uses_only_default_sets_and_prefers_animated():
    data = {"sets": {
        "3": {"emoticons": [{"name": "ZrehplaR", "urls": {"1": "//cdn.frankerfacez.com/emote/1/1", "2": "//cdn.frankerfacez.com/emote/1/2"},
                             "animated": {"2": "//cdn.frankerfacez.com/emote/1/animated/2"}}]},
        "9": {"emoticons": [{"name": "Private", "urls": {"1": "//cdn.frankerfacez.com/emote/9/1"}}]},
    }}
    out = parse_ffz_sets(data, only=[3])
    assert [e.name for e in out] == ["ZrehplaR"]
    assert out[0].url == "https://cdn.frankerfacez.com/emote/1/animated/2"


def test_image_urls_are_https_and_host_allowlisted():
    assert safe_image_url("//cdn.7tv.app/emote/X/2x.webp") == "https://cdn.7tv.app/emote/X/2x.webp"
    for bad in ("https://evil.example/x.png", "https://cdn.7tv.app.evil.example/x", "https://u@cdn.7tv.app/x",
                "https://cdn.7tv.app:8443/x", "javascript:alert(1)", "https://static-cdn.jtvnw.net/x"):
        assert safe_image_url(bad) is None, bad


def _service(*emotes_by_key):
    service = EmoteService(broadcaster_id="123", sources=PROVIDERS)
    for key, emotes in emotes_by_key:
        service._loaded[key] = emotes
    service._rebuild_index()
    return service


def test_decorate_replaces_words_keeps_other_fragments_and_plain_text():
    kekw = ThirdPartyEmote("KEKW", "https://cdn.7tv.app/emote/K/2x.webp")
    hat = ThirdPartyEmote("Hat", "https://cdn.7tv.app/emote/H/2x.webp", zero_width=True)
    service = _service((("channel", "7tv"), [kekw, hat]))
    twitch = {"type": "emote", "id": "25", "name": "Kappa", "animated": False}
    cheer = {"type": "cheermote", "name": "Cheer100", "prefix": "Cheer", "bits": 100, "tier": 100}
    out = service.decorate([{"type": "text", "text": "lol KEKW Hat unknown "}, twitch, cheer])
    assert out[0] == {"type": "text", "text": "lol "}
    assert out[1] == {"type": "emote", "name": "KEKW", "url": kekw.url, "zw": False}
    assert out[2] == {"type": "text", "text": " "}
    assert out[3] == {"type": "emote", "name": "Hat", "url": hat.url, "zw": True}
    assert out[4] == {"type": "text", "text": " unknown "}
    assert out[5:] == [twitch, cheer]


def test_precedence_channel_beats_global_and_7tv_beats_bttv_beats_ffz():
    def e(url_id):
        return ThirdPartyEmote("Pog", f"https://cdn.7tv.app/emote/{url_id}/2x.webp")

    service = _service((("global", "7tv"), [e("G7")]), (("channel", "ffz"), [e("CF")]), (("channel", "bttv"), [e("CB")]))
    assert service._index["Pog"].url.endswith("/CB/2x.webp")  # channel bttv beats channel ffz and global 7tv
    service = _service((("channel", "ffz"), [e("CF")]), (("channel", "7tv"), [e("C7")]), (("channel", "bttv"), [e("CB")]))
    assert service._index["Pog"].url.endswith("/C7/2x.webp")


def test_decorate_with_nothing_loaded_is_plain_text():
    service = EmoteService(broadcaster_id="123")
    assert service.decorate([{"type": "text", "text": "KEKW hi"}]) == [{"type": "text", "text": "KEKW hi"}]


def test_a_provider_that_is_down_keeps_previous_data_and_other_providers_still_load(monkeypatch):
    import pyxeetb.emotes as emotes

    kekw = ThirdPartyEmote("KEKW", "https://cdn.7tv.app/emote/K/2x.webp")
    bttv = ThirdPartyEmote("Sadge", "https://cdn.betterttv.net/emote/S/2x.webp")
    state = {"7tv_down": False}

    async def ok_7tv_global(session):
        return [kekw]

    async def flaky_7tv_channel(session, tid):
        if state["7tv_down"]:
            raise TimeoutError("7tv is down")
        return [kekw]

    async def down(session, *args):
        raise TimeoutError("down")

    async def ok_bttv(session, *args):
        return [bttv]

    async def empty(session, *args):
        return []

    monkeypatch.setattr(emotes, "_load_7tv_global", ok_7tv_global)
    monkeypatch.setattr(emotes, "_load_7tv_channel", flaky_7tv_channel)
    monkeypatch.setattr(emotes, "_load_bttv_global", ok_bttv)
    monkeypatch.setattr(emotes, "_load_bttv_channel", empty)
    monkeypatch.setattr(emotes, "_load_ffz_global", empty)
    monkeypatch.setattr(emotes, "_load_ffz_channel", empty)

    async def go():
        service = EmoteService(broadcaster_id="123")
        assert await service.refresh(None)  # type: ignore[arg-type]
        assert {"KEKW", "Sadge"} <= set(service._index)
        state["7tv_down"] = True
        assert await service.refresh(None)  # type: ignore[arg-type]  # bttv/ffz still succeed
        assert "KEKW" in service._index  # 7tv's last good data is kept
        # Everything down -> refresh reports failure (the runner retries sooner) but nothing is lost.
        for name in ("_load_7tv_global", "_load_bttv_global", "_load_bttv_channel", "_load_ffz_global", "_load_ffz_channel"):
            monkeypatch.setattr(emotes, name, down)
        assert not await service.refresh(None)  # type: ignore[arg-type]
        assert "KEKW" in service._index

    run(go())


def test_a_non_numeric_broadcaster_id_disables_providers_instead_of_crashing():
    assert not EmoteService(broadcaster_id="somename").enabled


def test_run_returns_at_once_when_disabled():
    service = EmoteService(broadcaster_id="123", sources=())
    asyncio.run(asyncio.wait_for(service.run(), timeout=1))


def test_provider_env_parsing(monkeypatch):
    monkeypatch.delenv("TWITCH_EMOTE_PROVIDERS", raising=False)
    assert _emote_providers_env("TWITCH_EMOTE_PROVIDERS") == PROVIDERS
    monkeypatch.setenv("TWITCH_EMOTE_PROVIDERS", "none")
    assert _emote_providers_env("TWITCH_EMOTE_PROVIDERS") == ()
    monkeypatch.setenv("TWITCH_EMOTE_PROVIDERS", "7tv, ffz, nonsense")
    assert _emote_providers_env("TWITCH_EMOTE_PROVIDERS") == ("7tv", "ffz")
