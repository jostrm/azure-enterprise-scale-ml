"""Offline: ARM leaves out a parent's child list once its last child is deleted; that is not a changed parent.

aif-138 (2026-11-02): the resumed factory deletion's common stage deleted kv-cmnadmdev-6hc2h-001's only private endpoint
connection. The vault's GET then left out properties.privateEndpointConnections, while the review minus the deleted
connection was an empty list, so the next check stopped with project-retained-parent-changed.
"""

from .test_factory_lifecycle import fl

KV = ("/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
      "/providers/Microsoft.KeyVault/vaults/kv-cmnadmdev-6hc2h-001")
CONNECTION = KV + "/privateEndpointConnections/pend-kv-cmnadmdev-6hc2h-001-to-vnt-esmlcmn"
OTHER = KV + "/privateEndpointConnections/pend-other"


def vault(*connections, **properties):
    body = {"id": KV, "type": "Microsoft.KeyVault/vaults",
            "properties": {"enableRbacAuthorization": True, "sku": {"name": "standard"}, **properties}}
    if connections is not None:
        body["properties"]["privateEndpointConnections"] = [
            {"id": identifier, "properties": {"privateEndpoint": {"id": identifier + "-pe"}}} for identifier in connections]
    return body


def compare(live, frozen, removed):
    gone = {value.lower() for value in removed}
    return (fl.fingerprint_body(fl._without_deleted_children(live, gone))
            == fl.fingerprint_body(fl._without_deleted_children(frozen, gone)))


def test_a_child_list_left_out_after_its_last_child_was_deleted_matches():
    live = vault()
    live["properties"].pop("privateEndpointConnections")
    assert compare(live, vault(CONNECTION), {CONNECTION})


def test_an_empty_child_list_after_its_last_child_was_deleted_matches():
    assert compare(vault(), vault(CONNECTION), {CONNECTION})


def test_a_remaining_child_and_a_changed_setting_still_count():
    assert not compare(vault(OTHER), vault(CONNECTION), {CONNECTION})
    live = vault(enableRbacAuthorization=False)
    live["properties"].pop("privateEndpointConnections")
    assert not compare(live, vault(CONNECTION), {CONNECTION})
