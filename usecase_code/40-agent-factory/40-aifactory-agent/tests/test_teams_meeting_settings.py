from uuid import UUID

import pytest
from pydantic import ValidationError

from aifactory_agent.teams_meeting_settings import MeetingPolicy, TeamsMeetingSettings, validate_meeting_url


HOST = "22222222-2222-4222-8222-222222222222"
LISTENER = "33333333-3333-4333-8333-333333333333"
URL = "https://teams.microsoft.com/meet/1234567890123?p=approved-secret"
EXTERNAL_TENANT = "88888888-8888-4888-8888-888888888888"
EXTERNAL_LISTENERS = [
    "55555555-5555-4555-8555-555555555555",
    "66666666-6666-4666-8666-666666666666",
    "77777777-7777-4777-8777-777777777777",
]


def enabled_config(**changes):
    return {
        "enabled": True,
        "acs_endpoint": "https://meeting-bridge.communication.azure.com",
        "allowed_host_object_ids": [HOST],
        "connect_origins": ["https://calling.example.com", "wss://calling.example.com"],
        "policies": [{
            "id": "review",
            "scope_key": "project001-dev",
            "meeting_url": URL,
            "meeting_safe_knowledge": True,
            "allowed_participant_object_ids": [HOST, LISTENER],
        }],
        **changes,
    }


def external_policy(**changes):
    return {
        **enabled_config()["policies"][0],
        "meeting_tenant_id": EXTERNAL_TENANT,
        "external_audience_disclosure_approved": True,
        "allowed_participant_object_ids": EXTERNAL_LISTENERS[:],
        **changes,
    }


def test_meeting_tenant_and_external_disclosure_default_to_existing_same_tenant_policy():
    policy = TeamsMeetingSettings.model_validate(enabled_config()).policies[0]
    assert policy.meeting_tenant_id is None
    assert policy.external_audience_disclosure_approved is False
    assert policy.model_dump(mode="json")["meeting_tenant_id"] is None


def test_external_disclosure_is_explicit_and_preserves_exact_roster_without_synthesizing_ids():
    policy = MeetingPolicy.model_validate(external_policy())
    assert policy.meeting_tenant_id == UUID(EXTERNAL_TENANT)
    assert policy.external_audience_disclosure_approved is True
    dumped = policy.model_dump(mode="json")
    assert dumped["meeting_tenant_id"] == EXTERNAL_TENANT
    assert dumped["allowed_participant_object_ids"] == EXTERNAL_LISTENERS


@pytest.mark.parametrize("changes", [
    {"meeting_tenant_id": None},
    {"meeting_tenant_id": "00000000-0000-0000-0000-000000000000"},
    {"meeting_tenant_id": "not-a-tenant"},
    {"meeting_safe_knowledge": False},
    {"allowed_participant_object_ids": []},
    {"allowed_participant_object_ids": EXTERNAL_LISTENERS * 2},
    {"allowed_participant_object_ids": [f"{number:08x}-1111-4111-8111-111111111111" for number in range(33)]},
    {"allowed_participant_object_ids": ["00000000-0000-0000-0000-000000000000"]},
    {"external_audience_disclosure_approved": "true"},
    {"external_audience_disclosure_approved": 1},
])
def test_external_disclosure_requires_explicit_tenant_whole_scope_approval_and_bounded_roster(changes):
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(policies=[external_policy(**changes)]))


def test_meeting_tenant_cannot_be_zero_even_without_external_disclosure():
    policy = enabled_config()["policies"][0]
    policy["meeting_tenant_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ValidationError):
        MeetingPolicy.model_validate(policy)


def test_disabled_by_default_and_enabled_policy_is_explicit():
    assert TeamsMeetingSettings().enabled is False
    for missing in ("acs_endpoint", "allowed_host_object_ids", "policies", "connect_origins"):
        config = enabled_config()
        del config[missing]
        with pytest.raises(ValidationError):
            TeamsMeetingSettings.model_validate(config)
    config = enabled_config()
    config["policies"][0]["meeting_safe_knowledge"] = False
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(config)
    assert TeamsMeetingSettings.model_validate(enabled_config()).max_session_seconds <= 3600


@pytest.mark.parametrize("listeners", [
    [], [LISTENER, LISTENER], ["00000000-0000-0000-0000-000000000000"],
    ["not-an-object-id"], [f"{number:08x}-1111-4111-8111-111111111111" for number in range(33)],
])
def test_enabled_policy_requires_bounded_distinct_nonzero_listener_ids(listeners):
    config = enabled_config()
    config["policies"][0]["allowed_participant_object_ids"] = listeners
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(config)


def test_listener_approval_is_required_and_preserved_as_uuid_values():
    config = enabled_config()
    settings = TeamsMeetingSettings.model_validate(config)
    assert [str(value) for value in settings.policies[0].allowed_participant_object_ids] == [HOST, LISTENER]
    del config["policies"][0]["allowed_participant_object_ids"]
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(config)


@pytest.mark.parametrize("url", [
    "http://teams.microsoft.com/meet/123",
    "https://teams.microsoft.com.evil.example/meet/123",
    "https://teams.microsoft.com@evil.example/meet/123",
    "https://user@teams.microsoft.com/meet/123",
    "https://teams.microsoft.com:444/meet/123",
    "https://teams.microsoft.com/meet/123#fragment",
    "https://teams.microsoft.com/../../meet/123",
    "https://teams.microsoft.com/meet/123\n",
    "https://teams.microsoft.com/l/channel/123",
    "https://teams.live.com/meet/123",
    "https://127.0.0.1/meet/123",
])
def test_rejects_non_meeting_and_ambiguous_urls(url):
    with pytest.raises(ValueError):
        validate_meeting_url(url)


def test_accepts_exact_teams_meeting_links_without_fetching():
    assert validate_meeting_url(URL) == URL
    link = ("https://teams.microsoft.com/l/meetup-join/"
            "19%3ameeting_abc123%40thread.v2/0?context=%7B%22Tid%22%3A%22tenant%22%7D")
    assert validate_meeting_url(link) == link


@pytest.mark.parametrize("endpoint", [
    "https://evil.example", "https://x.communication.azure.com/path",
    "https://x.communication.azure.com?secret=1", "http://x.communication.azure.com",
    "https://x.europe.communication.azure.com.evil.example",
    "https://user@x.europe.communication.azure.com",
    "https://x.europe.communication.azure.com:444",
    "https://x.region.extra.communication.azure.com",
    "https://x..communication.azure.com",
    "https://x.-europe.communication.azure.com",
])
def test_acs_endpoint_cannot_be_used_as_an_arbitrary_fetch_target(endpoint):
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(acs_endpoint=endpoint))


@pytest.mark.parametrize("endpoint", [
    "https://meeting-bridge.communication.azure.com",
    "https://meeting-bridge.europe.communication.azure.com",
    "https://meeting-bridge.unitedstates.communication.azure.com/",
])
def test_acs_accepts_global_and_single_regional_service_hostnames(endpoint):
    settings = TeamsMeetingSettings.model_validate(enabled_config(acs_endpoint=endpoint))
    assert settings.acs_endpoint == endpoint.rstrip("/")


@pytest.mark.parametrize("origin", [
    "https:", "wss:", "*", "https://*.skype.com", "https://teams.microsoft.com; script-src *",
    "https://teams.microsoft.com:80", "https://teams.microsoft.com/path",
    "https://user@teams.microsoft.com", "https://*.com", "https://teams.microsoft.com\n",
    "https://teams.microsoft.com?query=1", "https://teams.microsoft.com#fragment",
    "https://teams.microsoft.com?", "https://teams.microsoft.com#", "https://@teams.microsoft.com",
    "https://teams.microsoft.com:", "https://teams.microsoft.com:444", "http://teams.microsoft.com",
    "https://[::1]extra", "https://[fe80::1%25interface]",
])
def test_csp_cannot_be_broadened_or_injected_through_connection_origins(origin):
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(connect_origins=[origin]))


def test_csp_origins_are_exact_operator_data_not_guessed_service_families():
    settings = TeamsMeetingSettings.model_validate(enabled_config(connect_origins=[
        "https://Calling.Custom-Deployment.example:443/", "wss://calling.custom-deployment.example",
    ]))
    assert settings.connect_origins == [
        "https://calling.custom-deployment.example", "wss://calling.custom-deployment.example",
    ]
    with pytest.raises(ValidationError):
        TeamsMeetingSettings.model_validate(enabled_config(connect_origins=[
            "https://calling.example", "https://calling.example:443/",
        ]))
