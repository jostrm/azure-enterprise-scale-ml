# ESAIF Tutorials for Windows

**0.2.0 is a development-only local preview, not a published release.**
The explicitly selected local mode bundles nonconfidential tutorial guides behind an
invitation-code UI gate for a few trusted users. The protected API mode does not bundle guides.
Neither mode supplies an approved recording catalog.
There is currently no approved production host, signing identity, complete recording
catalog or public download established by this directory.

Release-scoped destination, **only after separately approved publication**:
[TutorialApp 0.2.0](https://github.com/jostrm/azure-enterprise-scale-ml/releases/tag/tutorialapp-v0.2.0).
This is not a claim that the release exists. Never use `/releases/latest`: ConfigWizard
and other products share the repository. See [candidate record](releases/v0.2.0/release.json)
and [notes](releases/v0.2.0/release-notes.md).

## Install and support

- Windows **11 x64**, build 22000 or newer. Per-user Inno Setup EXE; no admin required.
- Self-contained .NET and Windows App SDK. No Python, Node.js or WebView2 requirement.
- Native Windows codecs are required. Windows N may need the official Media Feature
  Pack from Windows optional features; no third-party codec pack is recommended.
- Check the version-specific SHA256 manifest and production publisher signature
  **before** running an installer. Unsigned `development-only` artifacts are local tests.
  Do not disable SmartScreen, enterprise controls or malware protection to run them.
- **Local preview:** `-LocalPreview -DevelopmentOnly` uses the existing salted verifier
  and bundled guides, without a server. At **Preview Code To Enter**, the invitation
  unlocks enabled tutorials for the current session. This is not a confidentiality
  boundary: guides and the verifier can be extracted, and there is no server revocation
  or expiry. Do not put an actual invitation code in source, logs, commands or documentation.
- **Protected API mode:** an approved online service and entitlement are required. No offline protected catalog,
  guide or video cache is distributed. At **Preview Code To Enter**, a valid server-
  checked preview code unlocks all enabled tutorials for the authorized session.
  The cohort being small does not bypass validation. A blank catalog is **not completed delivery**.
- Settings/progress belong under `%LOCALAPPDATA%\ESAIF.TutorialApp`, outside binaries.
  Upgrades and uninstall retain that state. Tokens and license keys must not be stored there.

See [SUPPORT.txt](SUPPORT.txt). Proprietary rights are separate from third-party licenses.
The inventory produced by tooling is **not** license certification.

## One repeatable local packaging chain

Prerequisites: PowerShell 7.4+, .NET 10 SDK plus the existing MAUI Windows workload,
the shared Asom build wrapper, source project references, and an existing Inno Setup 6
compiler. No installer/tool download is performed. Builds must run on Windows.
The historical ConfigWizard compiler may be passed explicitly if already installed:
`C:\Users\jostrm\source\repos\ESAIF.ConfigWizard\artifacts\installer-tools\InnoSetup\ISCC.exe`.

Run from this directory after the owner has configured the ignored
`src\ESAIF.TutorialApp\previewcode.local.json` using the app's secure-input setup tool.
The script validates that only the expected salt, verifier, work factor and schema exist;
it never requests or logs the invitation code. This local build is unsigned:

```powershell
$parameters = @{
    SourceRoot = 'C:\Users\jostrm\source\repos\ESAIF.TutorialApp'
    OutputRoot = Join-Path $PWD ('artifacts\local-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Version = '0.2.0'
    DevelopmentOnly = $true
    LocalPreview = $true
    InnoCompiler = 'C:\Users\jostrm\source\repos\ESAIF.ConfigWizard\artifacts\installer-tools\InnoSetup\ISCC.exe'
}
# Offline checks only: no build, output, signing, install or publication.
.\scripts\Publish-TutorialApp.ps1 @parameters -ValidateOnly
# Only after source is stable and the local build is authorized:
.\scripts\Publish-TutorialApp.ps1 @parameters
```

For protected API mode, omit `LocalPreview` and supply `ApiBaseUri`. The two options
cannot be combined. `https://preview.example.invalid/` is a deliberately nonfunctional
development placeholder, not a working service. `LocalPreview` is rejected unless
`DevelopmentOnly` is present, even if signing options are provided.

The script calls the **shared** `Invoke-AsomDotnet.ps1` in a child PowerShell process
(its machine-wide mutex serializes shared projects), never the app's `my-build.ps1`.
It publishes Release `win-x64`, self-contained with `WindowsAppSDKSelfContained=true`
and `TutorialAuthoring=false`; it explicitly sets `TutorialLocalPreview=true` only for
local mode and **false** otherwise, overriding any source-local auto-detection.
The app's separate macOS conditional target is untouched.
It overrides the preview version only for this publish.

Build and restore outputs use `--artifacts-path` in a unique ignored private staging
directory, separated by project. Neither existing source `bin`/`obj` nor an earlier
authoring build is a publish input. Existing release directories
are immutable: rerunning the same version/output root fails instead of replacing them.
Choose a new version or a new ignored output root. `last-successful-build` is never
copied, deleted, moved or replaced. Build logs, source details and private PDBs stay
under `artifacts\staging\<run>\private`, not in public release assets.

The source fingerprint covers local application and referenced owned source trees,
excluding build/runtime output directories. It records file hashes, observed Git HEADs
and dirty status. `-SourceRevision` is an optional claim, not proof HEAD equals inputs.
Dirty inputs warn rather than failing merely because they differ from Git. A changed
fingerprint during build fails the candidate. Keep builds stable while packaging.
This is provenance, **not** a bit-for-bit reproducible-build certification.

Before packaging, the chain rejects recordings, private settings/key files and PDBs.
Protected mode additionally rejects all bundled guides, catalogs and local verifiers.
Local mode allows only the fingerprint-matched `Tutorials` guide tree (including tutorial
source examples), root `tutorialcatalog.json` and the validated root salted verifier.
It checks guide presence, keeps secret/path scans, and removes unused server endpoint settings.
Its manifest declares `accessMode: local-invitation-gate/nonconfidential-guides`.
It maps owned source paths and scans owned ESAIF/Asom binaries for workstation paths.
In protected API mode, `previewsettings.json` contains exactly one
public HTTPS `PreviewApiBaseUri`, with no token, provider path or license key.
The installed client also recognizes the public `ESAIF_PREVIEW_API_URL` environment
override; this is an endpoint, never a credential. The endpoint
check is syntactic, does not contact the host and is not DNS/SSRF certification.

NuGet metadata from restored project assets is inventoried: package identities,
license expressions/URLs and available license/notice texts are included in `Licenses`.
Runtime notices remain bundled. Actual application font names/hashes are inventoried;
OpenSans copyright/license statements read from the two current fonts and the official
Apache-2.0 license text are included in `Licenses\Fonts`. Compare font hashes on release;
replacement/additional fonts require their own attribution review.
Full proprietor-approved license terms are supplied
via `-ProprietaryLicensePath`; the local fallback notice grants no license. Review all
third-party, runtime/SDK and font redistribution terms before approval.

## Recording catalog

`catalog\videos.example.json` intentionally contains **zero recordings**, no invented
durations, and no credentials. It is schema-valid but incomplete.

```powershell
.\scripts\Validate-VideoCatalog.ps1 `
    -CatalogPath .\catalog\videos.example.json `
    -ManifestPath 'C:\Users\jostrm\source\repos\ESAIF.TutorialApp\src\ESAIF.TutorialApp\Tutorials\esaif-python-sdk-01\tutorial.json'
```

Schema version 1 uses `catalogRevision`, `tutorialId`, and `videos` with `videoId`,
`scenarioId`, `title`, `displayOrder`, `mediaRef`; optional `description`,
`durationSeconds` (only after measurement), `language`, `posterMediaRef`, `captionMediaRef`.
Media references are opaque identifiers, never URLs, paths or provider credentials.
`displayOrder` is an integer **1–100**, unique across the whole catalog (never 0).
Each represented scenario has exactly one video, which is its primary recording.
Video identities are unique; optional durations must be positive and finite.

The selected manifest must match `tutorialId` and contain exactly one of each core ID.
Default manifest: `esaif-python-sdk-01`, current source titles:

| ID | Source scenario title |
|---|---|
| scenario-1 | Scenario 1: Init AI Factory |
| scenario-2 | Scenario 2: Add scaleset |
| scenario-3 | Scenario 3: Add or update project |
| scenario-4 | Scenario 4: Delete project |
| scenario-5 | Scenario 5: Delete scaleset |
| scenario-6 | Scenario 6: Delete AI Factory |

`-RequireComplete` requires all six primary entries and video titles matching the
selected manifest's scenario titles exactly. Another tutorial variant's titles are
not interchangeable. Validation proves structure, not
that a recording exists, is correct, approved or playable. The publish chain requires
`-ServiceApprovalReference` with `-RequireComplete`; use only after the actual protected
service and recordings are reviewed. Catalogs remain service-side; none are copied into
the public installer or release assets.

## Production gates: not authorized by these instructions

Remove `DevelopmentOnly` **only** after separate production approval. The chain requires:

- `-SigningApproved`, `-SignToolPath`, `-CertificateThumbprint`, `-TimestampUri` for an
  approved certificate already available in the user's certificate store. No passwords,
  PFX files or credential acquisition are implemented. The timestamp endpoint must be
  an approved trusted HTTPS RFC3161 service, not an arbitrary placeholder.
- `-ProprietaryLicensePath` and `-LicenseReviewApproved`.
- Real `-ApiBaseUri`, complete `-VideoCatalogPath`, `-RequireComplete`, and an actual
  `-ServiceApprovalReference`. No default production license lifetime is chosen.
- Human verification of native playback, license expiry/revocation, service restart,
  upgrade/downgrade and uninstall on supported Windows installations.

Owned executables/DLLs are signed before Inno compiles. Inno signs the **installer and
uninstaller**; the chain verifies publisher identity and a timestamp on owned binaries
and installer. Verify the installed uninstaller signature in a disposable Windows
acceptance environment before public approval. SHA256 manifests are generated **after**
signing. Private symbols, signing configuration, payload and staging are not release assets.
Every release asset must be **strictly below 2 GiB**. GitHub Releases is the intended
binary destination, not Git history. There is deliberately **no upload, release-create,
push, deploy, DNS, domain purchase or secret-creation operation** in this chain.

After separate authorization, a human publishes reviewed assets under the product-
scoped tag `tutorialapp-v<version>` and updates the landing link to that exact tag.
Do not upload `artifacts\staging` or any private build directory.

## Upgrade, rollback and data retention

The installer has its own AppId (different from ConfigWizard), fixed per-user install
root, and versioned binary directories. New dependencies cannot merge with old-version
dependencies. Shortcuts point to the installed version. Old version binaries may remain
until uninstall; personal state is outside all version directories.

Older installers refuse a newer installed version unless explicitly run with
`/ALLOWDOWNGRADE=1`. This is a deliberate compatibility acknowledgment, not automatic
state migration. Close the app and back up personal state; confirm an older client can
read it. An explicit uninstall/reinstall gives clean binaries while retaining state.
Never delete unrelated application directories. This tooling does not automate rollback.

## Validation

```powershell
.\tests\Test-Distribution.ps1 -SourceRoot 'C:\Users\jostrm\source\repos\ESAIF.TutorialApp'
# Includes synthetic packaging and compiles (but never executes) an inert Inno fixture:
.\tests\Test-Distribution.ps1 `
    -SourceRoot 'C:\Users\jostrm\source\repos\ESAIF.TutorialApp' -ExercisePackaging `
    -InnoCompiler 'C:\Users\jostrm\source\repos\ESAIF.ConfigWizard\artifacts\installer-tools\InnoSetup\ISCC.exe'
```

Tests create synthetic metadata and inert package fixtures only in `tests\.work-*`
and clean them up. They do not
record fake deliverable videos, contact services, invoke the app build or install anything.
See [hosting instructions](hosting/README.md) for the approval-gated server design.

## Evidence boundary

Implementation was checked against current TutorialApp manifest/project source and
ConfigWizard's existing installer conventions. Architecture intent references:
`documentation\architecture\contracts\Packaging-and-Release.md` (source versus installed
state) and `governance\Trust-and-Authorization.md` (separate approval and corpus boundaries).
Graph snapshot `133ef9d1b8bf819ac569c70e7f3aeadd2266de76667a1ee6510a85b61de00275`
was **stale** on inspection; current bounded source was used. This new directory is not
claimed graph-indexed. No graph refresh, runtime deployment or production verification
is implied by documentation or successful local tests.

## Verify the local candidate

The generated `<OutputRoot>\releases\v0.2.0\release.json` records its actual local installer
path, bytes, SHA256, observed Authenticode state, source fingerprint and elapsed build time.
Do not treat the planned GitHub URL as a working download. For example:

```powershell
$record = Get-Content (Join-Path $parameters.OutputRoot 'releases\v0.2.0\release.json') -Raw | ConvertFrom-Json
$installer = $record.artifacts[0].localPath
Get-Item -LiteralPath $installer | Select-Object FullName, Length
Get-FileHash -LiteralPath $installer -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $installer | Select-Object Status, SignerCertificate
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ine $record.artifacts[0].sha256) {
    throw 'Installer hash mismatch'
}
```

Local mode needs no API endpoint; the API example `.invalid` endpoint cannot work.
Recordings remain disabled/unavailable, including missing Scenario 6 coverage.
No invitation-code disclosure, service credentials, six-video delivery, Windows N codec test, clean-machine test or
production readiness is implied. Local native installation/upgrade/uninstall acceptance
must be recorded separately; this script compiles but does not execute the installer.
Close only the intended app yourself before installation; Inno does not terminate any app.
