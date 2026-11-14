"""Scope-bounded canonical proposals and receipt-derived catalog transitions."""

import copy
from uuid import NAMESPACE_URL, uuid5

import pipeline_inputs
from pipeline_lifecycle import digest, require, verified_outcome


CONTRACT = "pipeline-configuration-v1"


def semantic(document):
    return {key: value for key, value in document.items() if key != "generation"}


def _factory(document, identifier):
    return next((row for row in document["factories"] if row["id"] == identifier), None)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def _diff(before, after, path=""):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [row for key in sorted(before.keys() | after.keys())
                for row in _diff(before.get(key), after.get(key), path + "/" + key)]
    return [{"path": path, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]


def _project_proposal(expected, proposal, snapshot):
    factory_id = snapshot["factory"]["id"]
    before, after = _factory(expected, factory_id), _factory(proposal, factory_id)
    selected = snapshot["projects"][0]
    prior = _by_id(before["projects"]).get(selected["id"])
    scale_id = snapshot["scales"][0]["id"]
    place = {"environment": snapshot["request"]["environment"], "scale_set_id": scale_id}
    require(place in selected["placements"], "proposal-project-placement-required")
    if prior:
        require({k: v for k, v in prior.items() if k != "placements"}
                == {k: v for k, v in selected.items() if k != "placements"}, "proposal-project-identity-changed")
        require(selected["placements"] == prior["placements"]
                or selected["placements"] == [*prior["placements"], place],
                "proposal-project-placement-move-forbidden")
    else:
        require(selected.get("status") == "draft" and selected["placements"] == [place],
                "new-project-draft-required")
    selected_id = selected["id"]
    expected_projects = _by_id(before["projects"])
    expected_projects[selected_id] = copy.deepcopy(selected)
    require(_by_id(after["projects"]) == expected_projects, "configuration-outside-reviewed-scope")
    before["projects"] = copy.deepcopy(after["projects"])
    old_config = expected["configurations"][factory_id]
    new_config = proposal["configurations"][factory_id]
    old_values = old_config["variables"].get(selected_id)
    new_values = new_config["variables"][selected_id]
    if old_values:
        section = "dev" if place["environment"] == "dev" else "stage_prod"
        other = "stage_prod" if section == "dev" else "dev"
        require(old_values[other] == new_values[other], "configuration-outside-reviewed-scope")
        if section == "stage_prod" and any(
                row["environment"] in ("stage", "prod") and row["environment"] != place["environment"]
                for row in selected["placements"]):
            require(old_values[section] == new_values[section], "shared-stage-prod-configuration-requires-separate-review")
    old_config["projects"][selected_id] = copy.deepcopy(new_config["projects"][selected_id])
    old_config["variables"][selected_id] = copy.deepcopy(new_values)


def prepare_change(snapshot, canonical):
    proposal = snapshot["document"]
    baseline = canonical["document"]
    pipeline_inputs.validate_register(baseline)
    pipeline_inputs.validate_register(proposal)
    require(canonical["revision"] == digest(baseline), "canonical-revision-invalid")
    expected = copy.deepcopy(baseline)
    scenario, factory_id = snapshot["request"]["scenario"], snapshot["factory"]["id"]
    before, after = _factory(expected, factory_id), _factory(proposal, factory_id)
    require(after is not None, "proposal-factory-required")
    if before is None:
        require(scenario == 1 and len(after["scale_sets"]) == 1 and len(after["projects"]) == 1
                and after["status"] == "draft" and all(
                    row["status"] == "draft" and not row["owned_resource_ids"] for row in after["scale_sets"])
                and not proposal["bindings"].get(factory_id), "new-factory-draft-required")
        expected["factories"].append(copy.deepcopy(after))
        expected["configurations"][factory_id] = copy.deepcopy(proposal["configurations"][factory_id])
    elif scenario in (1, 2):
        require({k: v for k, v in before.items() if k not in ("scale_sets", "projects")}
                == {k: v for k, v in after.items() if k not in ("scale_sets", "projects")},
                "proposal-factory-identity-changed")
        scale = snapshot["scales"][0]
        scales = _by_id(before["scale_sets"])
        if scale["id"] not in scales:
            require(scale["status"] == "draft" and not scale["owned_resource_ids"], "new-scale-draft-required")
            scales[scale["id"]] = copy.deepcopy(scale)
            expected["configurations"][factory_id]["scale_sets"][scale["id"]] = copy.deepcopy(
                proposal["configurations"][factory_id]["scale_sets"][scale["id"]])
        require(_by_id(after["scale_sets"]) == scales, "configuration-outside-reviewed-scope")
        before["scale_sets"] = copy.deepcopy(after["scale_sets"])
        if scenario == 1:
            require(len(before["scale_sets"]) == 1, "initialization-cannot-update-existing-factory-cohort")
            _project_proposal(expected, proposal, snapshot)
            expected["configurations"][factory_id]["factory"] = copy.deepcopy(
                proposal["configurations"][factory_id]["factory"])
            expected["configurations"][factory_id]["scale_sets"][scale["id"]] = copy.deepcopy(
                proposal["configurations"][factory_id]["scale_sets"][scale["id"]])
    elif scenario == 3:
        require(before is not None, "proposal-existing-factory-required")
        _project_proposal(expected, proposal, snapshot)
    require(semantic(expected) == semantic(proposal), "configuration-outside-reviewed-scope")
    return {"contract": CONTRACT, "baseline": copy.deepcopy(canonical), "proposal": copy.deepcopy(proposal),
            "changes": _diff(semantic(baseline), semantic(proposal)),
            "warnings": ["canonical-generation-drift"] if baseline["generation"] != proposal["generation"] else []}


def assert_baseline(change, canonical):
    require(change.get("contract") == CONTRACT
            and semantic(change["baseline"]["document"]) == semantic(canonical["document"]),
            "canonical-configuration-changed")


def prepare_recovery_change(snapshot, prior, plan, canonical):
    """Adopt only this operation's outcome after the native recovery proof."""
    change = prior["plan"].get("configuration")
    if change is None or semantic(change["baseline"]["document"]) == semantic(canonical["document"]):
        return prepare_change(snapshot, canonical)
    # Acquisition binds the current revision after allowing generation-only
    # drift; the claim's review digest, not revision equality, binds this plan.
    require(change == prepare_change(snapshot, change["baseline"]),
            "configuration-recovery-original-review-mismatch")
    stages = plan["stages"]
    require(len(stages) == 1 and stages[0].get("kind") == "retained-claim-reconciliation",
            "configuration-recovery-completed-proof-required")
    stage = stages[0]
    proof = stage["reconciliation"]
    require(proof.get("completed_outcome") is True and proof.get("canonical") == canonical
            and proof.get("prior_operation_id") == prior["operation_id"]
            and proof.get("prior_plan_hash") == prior["plan_hash"]
            and proof.get("prior_snapshot_hash") == digest(snapshot)
            and proof.get("prior_admission_claim") == prior["admission_claim"],
            "configuration-recovery-completed-proof-required")
    # These records were bound to the immutable native claims and freshly
    # observed by the recovery planner, not taken from journal success flags.
    children = [{"native": proof["native_records"]["runs/" + doc["run_id"] + ".json"],
                 "worker": proof["native_records"].get("runs/" + doc["run_id"] + ".worker.json")}
                for doc in stage["manifests"]]
    observed = copy.deepcopy(prior)
    observed["status"] = "continuation-required" if proof["continuation_required"] else "succeeded"
    observed["stages"] = [{"id": prior["plan"]["stages"][0]["id"], "status": "succeeded",
                          "observation": {"status": "succeeded", "verified": True, "children": children}}]
    require(canonical["revision"] == digest(canonical["document"])
            and canonical["document"] == completed_document(observed),
            "configuration-recovery-canonical-outcome-mismatch")
    return {"contract": CONTRACT, "baseline": copy.deepcopy(canonical),
            "proposal": copy.deepcopy(canonical["document"]), "changes": [],
            "warnings": ["canonical-outcome-already-published"]}


def _verified(record):
    stages, checkpoints = record["plan"]["stages"], record["stages"]
    require(len(stages) == len(checkpoints) and stages, "configuration-verified-stages-required")
    result = []
    for stage, checkpoint in zip(stages, checkpoints):
        receipt = checkpoint.get("observation", checkpoint.get("receipt", {}))
        require(stage["id"] == checkpoint["id"] and checkpoint["status"] == receipt.get("status")
                and verified_outcome(receipt),
                "configuration-verified-receipt-required")
        result.append((stage, receipt))
    return result


def _forget_placements(factory, config, scales, project_ids=None):
    for project in list(factory["projects"]):
        if project_ids is not None and project["id"] not in project_ids:
            continue
        project["placements"] = [place for place in project["placements"] if place["scale_set_id"] not in scales]
        if not project["placements"]:
            factory["projects"].remove(project)
            config["projects"].pop(project["id"])
            config["variables"].pop(project["id"])


def completed_document(record):
    snapshot = record["snapshot"]
    document = copy.deepcopy(snapshot["document"])
    pipeline_inputs.validate_register(document)
    factory_id, scenario = snapshot["factory"]["id"], snapshot["request"]["scenario"]
    factory = _factory(document, factory_id)
    config = document["configurations"][factory_id]
    scales = {scale["id"] for scale in snapshot["scales"]}
    verified = _verified(record)
    if len(verified) == 1 and verified[0][0]["kind"] == "bootstrap-enrollment":
        stage, receipt = verified[0]
        binding = receipt.get("binding_candidate")
        require(receipt.get("enrollment_complete") is True and receipt.get("status") == "continuation-required"
                and isinstance(binding, dict), "configuration-enrollment-not-verified")
        import factory_enrollment
        factory_enrollment._validate_binding(binding)
        request = stage["enrollment"]
        selected = [row for row in binding["targets"] if row["scale_set_id"] in scales]
        require(len(selected) == 1 and request["target"]["factory_id"] == factory_id
                and request["target"]["scaleset_id"] in scales
                and binding["repository"] == request["route"]["repository"]
                and binding["orchestrator"] == snapshot["request"]["provider"]
                and set(map(str.lower, selected[0]["resource_group_ids"])) == set(map(str.lower, request["scopes"]))
                and set(map(str.lower, selected[0].get("common_dependency_ids", [])))
                == set(map(str.lower, request["common_dependencies"])),
                "configuration-enrollment-binding-mismatch")
        previous = document["bindings"].get(factory_id, {}).get(binding["orchestrator"])
        if previous:
            retained = [row for row in previous["targets"] if row["scale_set_id"] not in scales]
            require(retained == [row for row in binding["targets"] if row["scale_set_id"] not in scales]
                    and all(previous[key] == binding[key] for key in ("repository", "ref", "shared_remote")),
                    "configuration-enrollment-unrelated-binding-changed")
        document["bindings"].setdefault(factory_id, {})[binding["orchestrator"]] = copy.deepcopy(binding)
        scale = next(row for row in factory["scale_sets"] if row["id"] in scales)
        resources = {value.lower(): value for value in scale["owned_resource_ids"] + request["scopes"]}
        scale["owned_resource_ids"] = sorted(resources.values(), key=str.lower)
        document["generation"] = str(uuid5(NAMESPACE_URL, CONTRACT + "/" + record["operation_id"] + "/" + digest(document)))
        pipeline_inputs.validate_register(document)
        return document
    manifests = [manifest for stage, _ in verified for manifest in stage.get("manifests", [])]
    children = [child for _, receipt in verified for child in receipt.get("children", [])]
    absent = {value.lower() for child in children for key in (
        "deleted_resources", "deleted_resource_groups", "observed_absent")
        for value in child.get("native", {}).get(key, [])}
    if scenario < 4:
        require(children and all(child.get("worker") for child in children), "configuration-verified-workers-required")
        known_scales = _by_id(factory["scale_sets"])
        for child in children:
            worker = child["worker"]
            target = worker.get("target", {})
            require(worker.get("status") == "succeeded" and target.get("factory_id") == factory_id
                    and target.get("scaleset_id") in scales, "configuration-worker-identity-mismatch")
            scale = known_scales[target["scaleset_id"]]
            resources = {value.lower(): value for value in scale["owned_resource_ids"]}
            for row in worker.get("resource_groups", []) + worker.get("ownership", []):
                owner = row.get("owner", {})
                require(owner.get("factory_id") == factory_id and owner.get("scaleset_id") == scale["id"],
                        "configuration-worker-ownership-mismatch")
                resource_id = row["resource_id"]
                resources[resource_id.lower()] = resource_id
                document.setdefault("ownership_evidence", {})[resource_id.lower()] = {
                    "owner": copy.deepcopy(owner), "ownership_source": "deployment-receipt",
                    "ownership_evidence": {"run_id": worker["run_id"], "receipt_hash": digest(worker)}}
            scale["owned_resource_ids"] = sorted(resources.values(), key=str.lower)
            if record["status"] != "continuation-required":
                scale["status"] = "configured"
        if record["status"] != "continuation-required":
            factory["status"] = "configured"
        if scenario in (1, 3) and record["status"] != "continuation-required":
            for project in factory["projects"]:
                if project["id"] in {row["id"] for row in snapshot["projects"]}:
                    project["status"] = "configured"
    elif scenario == 4:
        if snapshot["request"]["include_keyvault_and_resource_group"]:
            groups = {manifest.get("deletion", {}).get("project_resource_group", "").lower() for manifest in manifests}
            require(groups and "" not in groups and groups <= absent, "configuration-project-group-absence-required")
            _forget_placements(factory, config, scales, {row["id"] for row in snapshot["projects"]})
    else:
        reviewed_groups = {row["id"].lower() for manifest in manifests for row in
                           manifest.get("deletion", {}).get("resource_groups", []) if row.get("delete") is True}
        reviewed_resources = {row["id"].lower() for manifest in manifests for row in
                              manifest.get("deletion", {}).get("resources", []) if row.get("delete") is True}
        require(manifests and reviewed_groups | reviewed_resources <= absent,
                "configuration-deleted-group-absence-required")
        retained = {row.get("owner", {}).get("scaleset_id") for manifest in manifests
                    for row in manifest.get("deletion", {}).get("resource_groups", [])
                    + manifest.get("deletion", {}).get("resources", [])
                    if row.get("delete") is False and row.get("owner", {}).get("factory_id") == factory_id}
        removable = scales - retained
        _forget_placements(factory, config, removable)
        for manifest in manifests:
            scale_id = manifest["target"]["scaleset_id"]
            deleted_projects = {row.get("owner", {}).get("project_id")
                                for row in manifest.get("deletion", {}).get("resource_groups", [])
                                if row.get("delete") is True and row["id"].lower() in absent
                                and row.get("owner", {}).get("factory_id") == factory_id
                                and row.get("owner", {}).get("scaleset_id") == scale_id}
            _forget_placements(factory, config, {scale_id},
                               {project["id"] for project in factory["projects"]
                                if project["number"] in deleted_projects})
        if scenario == 5 or retained:
            factory["scale_sets"] = [row for row in factory["scale_sets"] if row["id"] not in removable]
            config["scale_sets"] = {key: value for key, value in config["scale_sets"].items() if key not in removable}
            for scale in factory["scale_sets"]:
                if scale["id"] in retained:
                    scale["owned_resource_ids"] = [value for value in scale["owned_resource_ids"]
                                                   if not any(value.lower() == gone or value.lower().startswith(gone + "/")
                                                              for gone in absent)]
            for provider, binding in list(document["bindings"].get(factory_id, {}).items()):
                binding["targets"] = [row for row in binding["targets"] if row["scale_set_id"] not in removable]
                if not binding["targets"]:
                    del document["bindings"][factory_id][provider]
        else:
            require(scales == {row["id"] for row in factory["scale_sets"]}, "configuration-complete-factory-required")
            document["factories"].remove(factory)
            document["configurations"].pop(factory_id)
            document["bindings"].pop(factory_id, None)
    if scenario >= 4:
        evidence = document.get("ownership_evidence", {})
        for key in list(evidence):
            if any(key.lower() == gone or key.lower().startswith(gone + "/") for gone in absent):
                del evidence[key]
    if semantic(document) != semantic(snapshot["document"]):
        document["generation"] = str(uuid5(NAMESPACE_URL, CONTRACT + "/" + record["operation_id"] + "/" + digest(document)))
    pipeline_inputs.validate_register(document)
    return document
