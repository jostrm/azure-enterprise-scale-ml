"""Offline: a Bot Service channel's etag embeds the time it was read, so it never fingerprints the channel.

aif-144 (2026-11-04, delete_factory run7): confirmation looped on "inventory changed" for
botServices/<bot>/channels/DirectLineChannel, whose etag was W/"...11/4/2026 5:46:27 PM" and differed on every read.
"""

from .test_factory_lifecycle import fl

KIND = "microsoft.botservice/botservices/channels"


def channel(etag):
    return {"id": "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/"
                  "Microsoft.BotService/botServices/bot-001/channels/DirectLineChannel",
            "type": "Microsoft.BotService/botServices/channels", "location": "global", "etag": etag,
            "properties": {"channelName": "DirectLineChannel", "etag": etag, "properties": {"sites": []}}}


def test_a_bot_channel_etag_is_not_compared():
    assert fl.resource_etag(channel('W/"a 11/4/2026 5:46:27 PM"'), {}, KIND) is None


def test_two_reads_of_an_unchanged_channel_fingerprint_the_same():
    first, second = channel('W/"a 11/4/2026 5:46:27 PM"'), channel('W/"a 11/4/2026 5:47:02 PM"')
    assert fl.resource_digest(first, KIND) == fl.resource_digest(second, KIND)


def test_a_changed_channel_setting_still_changes_the_fingerprint():
    changed = channel('W/"a"')
    changed["properties"]["properties"]["sites"] = [{"siteName": "new"}]
    assert fl.resource_digest(channel('W/"a"'), KIND) != fl.resource_digest(changed, KIND)
