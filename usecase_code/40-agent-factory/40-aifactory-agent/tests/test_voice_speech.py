"""Pure text tests: no audio, Azure or network. Spoken text is a faithful, shorter rendition of the on-screen answer."""

import pytest

from aifactory_agent.speech import SpokenText, spoken_text


def say(text, **kwargs):
    return spoken_text(text, **kwargs)


def test_citation_markers_are_not_spoken_but_sources_stay_on_screen():
    result = say("Use the wizard [S1]. Graph evidence agrees [G2][A3].")
    assert result.text == "Use the wizard. Graph evidence agrees."
    assert not result.truncated and result.omitted == ()


def test_markdown_decoration_is_removed_and_links_keep_their_label():
    result = say("## Setup\n**Run** `azurefactory status` first.\n> Note: _read-only_.\nSee [the guide](https://example.com/guide).")
    assert result.text == "Setup. Run azurefactory status first. Note: read-only. See the guide."
    assert result.omitted == ()


def test_code_blocks_tables_and_bare_urls_are_omitted_and_announced():
    answer = (
        "Run this:\n```powershell\nGet-Date\n```\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n"
        "Docs: https://learn.microsoft.com/azure/ai-services/speech-service/voice-live ."
    )
    result = say(answer)
    assert "Get-Date" not in result.text and "|" not in result.text and "http" not in result.text
    assert result.omitted == ("code", "table", "link")
    assert result.text.endswith("The code, the table and the links are on screen.")


def test_lists_become_sentences_in_order():
    assert say("- first\n- second\n1. third").text == "first. second. third."


def test_identifiers_are_split_so_speech_does_not_spell_them_out():
    result = say("Set enableAIFactoryAgentLiveVoice and ENABLE_AI_FACTORY_MCP, not aifactory_agent. GitHub is fine.")
    assert result.text == "Set enable AI Factory Agent Live Voice and ENABLE AI FACTORY MCP, not aifactory agent. GitHub is fine."


def test_swedish_and_other_unicode_text_is_preserved():
    assert say("Så här gör du [S1]: öppna Fabriken.").text == "Så här gör du: öppna Fabriken."


def test_html_tags_are_dropped_not_read_aloud():
    assert say("Hello <script>alert(1)</script><b>world</b>.").text == "Hello alert(1)world."


def test_long_answers_stop_at_a_sentence_boundary_and_stay_within_the_limit():
    sentence = "This is a reasonably long sentence about the Factory. "
    result = say(sentence * 40, max_chars=300)
    assert result.truncated
    assert len(result.text) <= 300
    assert result.text.endswith("The full answer is on screen.")
    body = result.text[: -len(" The full answer is on screen.")]
    assert body.endswith(".") and body.count("Factory.") == body.count("sentence about")


def test_a_single_endless_sentence_is_cut_on_a_word_boundary():
    result = say("word " * 400, max_chars=200)
    assert result.truncated and len(result.text) <= 200
    assert "wor." not in result.text and "  " not in result.text


def test_empty_or_markup_only_input_yields_nothing_to_say():
    for value in ("", "   \n ", "[S1][S2]", "```\ncode only\n```x"):
        result = say(value)
        assert isinstance(result, SpokenText)
    assert say("").text == "" and say("[S1] [S2]").text == ""


def test_limit_is_validated():
    with pytest.raises(ValueError):
        say("text", max_chars=10)
