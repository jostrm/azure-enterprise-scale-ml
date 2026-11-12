# ESAIF Tutorials 0.2.0 — development-only candidate

Distribution tooling supports an explicitly selected local invitation preview and
a separate protected API packaging path.
This source record is **not a successful build, signed installer, public release,
hosted service or completed recording delivery**. No artifact checksum is fabricated.

- Windows 11 x64, per-user self-contained native client; no WebView2 requirement.
- Local development mode bundles nonconfidential guides and a salted invitation
  verifier. The UI gate is not server authorization or confidentiality; it has
  no server revocation or expiry. Protected API mode still bundles neither.
- Recordings remain unavailable; no complete video rollout is claimed.
- Empty example recording metadata is schema-valid but incomplete.
- Preview version 0.2.0 is distinct from the existing 0.1.0 authoring client.
- Existing successful app builds and personal settings/progress are preserved.

Local acceptance still requires integrated client validation/build and Windows
installer acceptance. Production blockers: real service endpoint/policy approval,
six approved primary recordings, owner-approved license notices, signing identity
and trusted timestamp configuration, Windows installer/playback acceptance.

Intended tag after separate approval: `tutorialapp-v0.2.0`.
No upload, publication or deployment has been performed by this tooling.
