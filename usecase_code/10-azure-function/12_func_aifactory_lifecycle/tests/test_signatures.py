import hashlib
import hmac

from aif_lifecycle.signatures import sign, verify

BODY = b'{"action":"completed"}'


def test_sign_matches_github_x_hub_signature_256():
    expected = "sha256=" + hmac.new(b"s3cret", BODY, hashlib.sha256).hexdigest()
    assert sign(b"s3cret", BODY) == expected


def test_verify_accepts_the_right_signature_only():
    header = sign(b"s3cret", BODY)
    assert verify([b"s3cret"], BODY, header)
    assert not verify([b"other"], BODY, header)
    assert not verify([b"s3cret"], BODY + b" ", header)


def test_verify_accepts_a_previous_secret_during_rotation():
    assert verify([b"new", b"old"], BODY, sign(b"old", BODY))


def test_verify_rejects_missing_malformed_or_unconfigured_signatures():
    assert not verify([b"s3cret"], BODY, None)
    assert not verify([b"s3cret"], BODY, "sha1=abc")
    assert not verify([b"s3cret"], BODY, "sha256=not-hex")
    assert not verify([], BODY, sign(b"s3cret", BODY))
