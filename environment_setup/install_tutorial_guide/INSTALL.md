# Install ESAF Tutorials on Windows

The lab guide app ships in this folder as one `.msi` plus its `.cab` parts, for example
`ESAF-Tutorials-0.2.0-win-x64-protected-unsigned.msi` with `...-1.cab` to `...-4.cab`.
The app includes the local Factory API, so no separate API install is needed.

1. Download the **`.msi` and all its `.cab` parts** into one folder. Keep the original file names.
2. Double-click the `.msi`. It installs for your Windows account into `%LOCALAPPDATA%\ESAF Tutorials`;
   administrator rights are not normally required.
3. Open **ESAF Tutorials** from Start.

**All `.cab` parts and the `.msi` are required.** The parts hold the compressed app; Windows Installer reads
them from beside the `.msi`. They are split so that no file reaches GitHub's 100 MiB limit. Run **only the
`.msi`**. `SHA256SUMS.txt` lists every file's hash; compare a download with
`Get-FileHash .\filename -Algorithm SHA256`.

**Unsigned preview:** Windows SmartScreen or your organization's application policy may warn or block
installation. Verify the download source and hashes and follow your organization's approval process; do not
disable security controls.

To update, run the newer `.msi` (with its parts). To remove the app, use
**Settings > Apps > Installed apps > ESAF Tutorials**. Older installers are kept in [old](old/) when a newer
version is published here.
