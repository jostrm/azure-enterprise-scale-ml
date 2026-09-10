"""Protected one-shot bridge: bind consent to in-memory manifest before runtime mutation."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import types


def execute(args):
    helper = Path(args.helper)
    source = helper.read_bytes()
    normalized = source.decode("utf-8").replace("\r\n", "\n")
    if hashlib.sha256(normalized.encode()).hexdigest() != args.helper_sha256:
        raise ValueError("reviewed-helper-changed")
    module = types.ModuleType("aifactory_reviewed_lifecycle")
    module.__file__ = str(helper)
    sys.path.insert(0, str(helper.parent))
    exec(compile(source, str(helper), "exec"), module.__dict__)
    protected = Path(args.protected_manifest)
    cohort = getattr(args, "cohort", False)
    if protected.stat().st_size > (128 if cohort else 8) * 1024 * 1024:
        raise ValueError("protected-manifest-too-large")
    raw = module.unprotect(protected.read_bytes())
    document = json.loads(raw.decode("utf-8"))
    if cohort:
        if not isinstance(document, list) or not document:
            raise ValueError("invalid-consented-cohort")
        hashes = []
        for child in document:
            if module.manifest_digest(child) != child.get("manifest_hash"):
                raise ValueError("consented-manifest-changed")
            hashes.append(child["manifest_hash"])
        expected = hashlib.sha256(json.dumps(sorted(hashes), separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        if expected != args.expected_hash or len(set(hashes)) != len(hashes):
            raise ValueError("consented-cohort-changed")
        if (module.capabilities().get("factory_cohort") != "physical-lease-cohort-v1"
                or not callable(getattr(module, "execute_cohort", None))):
            raise ValueError("published-cohort-runtime-required")
        for child in document:
            module.validate_manifest(child)
        return module.execute_cohort(document, args.source_root, args.execution_root, args.receipt)
    if module.manifest_digest(document) != args.expected_hash or document.get("manifest_hash") != args.expected_hash:
        raise ValueError("consented-manifest-changed")
    module.validate_manifest(document)
    receipt = module.execute(document, args.source_root, args.execution_root, args.receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("helper", "helper-sha256", "expected-hash", "protected-manifest", "source-root", "execution-root", "receipt"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--cohort", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print('{"status":"blocked","error_code":"reviewed-runtime-input-or-execution-failed"}')
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
