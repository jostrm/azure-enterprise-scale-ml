import {build} from "esbuild";
import {readFile, readdir, writeFile} from "node:fs/promises";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";

process.chdir(dirname(fileURLToPath(import.meta.url)));
const result = await build({
  entryPoints: ["sdk-entry.js"], bundle: true, platform: "browser", format: "iife",
  globalName: "ESAFMeetingSDK", target: "es2020", minify: true, legalComments: "inline",
  outfile: "../vendor/teams-meeting-sdk.min.js", metafile: true,
  banner: {js: "/*! Bundled ACS Calling 1.46.1 / Communication Common 2.5.0. " +
    "Licenses and supplier notices: /static/teams-meeting-frontend/THIRD-PARTY-NOTICES.txt */"},
});
if (Object.values(result.metafile.outputs).some(output => output.imports.length)) {
  throw new Error("Meeting SDK must be completely bundled without external browser imports.");
}
const packages = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  const parts = input.replaceAll("\\", "/").split("/");
  const index = parts.lastIndexOf("node_modules");
  if (index < 0) continue;
  const length = parts[index + 1].startsWith("@") ? index + 3 : index + 2;
  const root = resolve(parts.slice(0, length).join("/"));
  if (packages.has(root)) continue;
  const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
  packages.set(root, manifest);
}
const notices = [];
for (const [root, manifest] of [...packages.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name))) {
  notices.push(`${manifest.name} ${manifest.version}\nLicense: ${manifest.license || "See supplier license"}\n`);
  for (const name of (await readdir(root)).sort()) {
    if (/^(licen[cs]e|copying|notices|third.?party.?notices)(\.|$)/i.test(name)) {
      notices.push(`${name}\n${await readFile(join(root, name), "utf8")}\n`);
    }
  }
}
await writeFile("THIRD-PARTY-NOTICES.txt", notices.join("\n----------------------------------------\n"), "utf8");
