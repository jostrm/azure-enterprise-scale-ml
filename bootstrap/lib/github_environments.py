"""Resolve bootstrap environment names without renaming deployed OIDC bindings."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import quote

from factory_enrollment import Cloud, EnrollmentError, canonical, parse_json, require


VARIABLE = "AIFACTORY_GITHUB_ENVIRONMENTS"
DEFAULTS = {"dev": "Dev", "stage": "Stage", "prod": "Prod"}


class Repository:
    """Only gh authentication is needed; no registered factory or enrollment."""

    def __init__(self, repository):
        self.config = {"github_repository": repository}
        self.cloud = Cloud({})

    def environment(self, name):
        status, _, value = self.cloud.gh(
            "GET", "repos/" + self.config["github_repository"] + "/environments/" + quote(name, safe=""),
            allowed=(200, 404))
        return value if status == 200 else None

    def ensure_environment(self, name, expected):
        current = self.environment(name)
        if expected is not None:
            require(current == expected, "reviewed-github-environment-changed")
        if current is not None:
            return current
        _, _, repository = self.cloud.gh("GET", "repos/" + self.config["github_repository"])
        require(isinstance(repository.get("node_id"), str), "github-repository-node-required")
        # GraphQL creates or returns unchanged; REST PUT can overwrite protection rules.
        mutation = ("mutation($repository:ID!,$name:String!){createEnvironment(input:"
                    "{repositoryId:$repository,name:$name}){environment{id name}}}")
        self.cloud.read_only = False
        result = parse_json(self.cloud.command(
            ["gh", "api", "--hostname", "github.com", "--method", "POST", "graphql", "--input", "-"],
            canonical({"query": mutation, "variables": {"repository": repository["node_id"], "name": name}})))
        require(not result.get("errors"), "github-environment-create-not-verified")
        created = result.get("data", {}).get("createEnvironment", {}).get("environment") or {}
        actual = self.environment(name)
        require(actual and actual.get("name") == name and created.get("name") == name
                and actual.get("node_id") == created.get("id"), "github-environment-create-not-verified")
        return actual


def resolve(names, saved=None, requested=None):
    names = list(names)
    require(all(isinstance(name, str) for name in names), "invalid-github-environment-inventory")
    require(len({name.casefold() for name in names}) == len(names), "ambiguous-github-environments")
    for mapping in (saved, requested):
        if mapping is not None:
            require(isinstance(mapping, dict) and set(mapping) == set(DEFAULTS),
                    "github-environment-map-requires-dev-stage-prod")
            require(all(isinstance(value, str) and value.strip() == value
                        and 0 < len(value) <= 255 and not any(ord(char) < 32 for char in value)
                        for value in mapping.values()), "invalid-github-environment-name")
            require(len({value.casefold() for value in mapping.values()}) == 3,
                    "github-environments-must-be-distinct")
    require(saved is None or requested is None or saved == requested,
            "github-environment-migration-requires-explicit-review")
    explicit = saved or requested
    result = {}
    for logical, default in DEFAULTS.items():
        wanted = explicit[logical] if explicit else default
        matches = [name for name in names if name.casefold() == wanted.casefold()]
        actual = matches[0] if matches else wanted
        require(explicit is None or actual == wanted,
                "github-environment-case-differs-from-reviewed-binding")
        result[logical] = actual
    return result


def ensure(repository, selected, requested=None):
    endpoint = "repos/" + repository.config["github_repository"]
    inventory = parse_json(repository.cloud.command([
        "gh", "api", "--hostname", "github.com", "--paginate", "--slurp",
        endpoint + "/environments?per_page=100",
    ]))
    names = [item["name"] for page in inventory for item in page["environments"]]
    status, _, variable = repository.cloud.gh(
        "GET", endpoint + "/actions/variables/" + VARIABLE, allowed=(200, 404))
    saved = parse_json(variable["value"]) if status == 200 else None
    mapping = resolve(names, saved, requested)
    for logical in selected:
        name = mapping[logical]
        actual = repository.ensure_environment(name, repository.environment(name))
        require(actual["name"] == name, "github-environment-name-not-verified")
    repository.cloud.read_only = False
    if status == 404:
        repository.cloud.gh("POST", endpoint + "/actions/variables",
                            {"name": VARIABLE, "value": canonical(mapping).decode("utf-8")},
                            allowed=(201,))
    _, _, persisted = repository.cloud.gh("GET", endpoint + "/actions/variables/" + VARIABLE)
    require(parse_json(persisted["value"]) == mapping, "github-environment-map-not-verified")
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ensure", nargs="+", choices=tuple(DEFAULTS), required=True)
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository),
                "github-repository-slug-required")
        requested = os.environ.get(VARIABLE)
        mapping = ensure(Repository(args.repository),
                         args.ensure, parse_json(requested) if requested else None)
        print(json.dumps(mapping, separators=(",", ":")))
        return 0
    except EnrollmentError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
