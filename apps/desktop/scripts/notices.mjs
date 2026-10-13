import { execFileSync } from "node:child_process";
import {
  readFileSync,
  readdirSync,
  existsSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const metadata = JSON.parse(
  execFileSync(
    "cargo",
    [
      "metadata",
      "--locked",
      "--format-version",
      "1",
      "--manifest-path",
      join(desktop, "src-tauri/Cargo.toml"),
      "--filter-platform",
      "x86_64-pc-windows-msvc",
    ],
    { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
  ),
);
const nodes = new Map(metadata.resolve.nodes.map((node) => [node.id, node]));
const selected = new Set();
function visit(id) {
  if (selected.has(id)) return;
  selected.add(id);
  for (const dependency of nodes.get(id)?.dependencies || []) visit(dependency);
}
visit(metadata.resolve.root);
const missing = [];
const entries = [];
function licenses(directory, explicit) {
  if (!existsSync(directory)) return [];
  const files = readdirSync(directory).filter((name) =>
    /^(licen[cs]e|copying)([._-]|$)/i.test(name),
  );
  if (explicit)
    files.push(isAbsolute(explicit) ? explicit : join(directory, explicit));
  return [
    ...new Set(
      files.map((file) => (isAbsolute(file) ? file : join(directory, file))),
    ),
  ]
    .sort()
    .filter((file) => existsSync(file) && statSync(file).isFile())
    .map((file) => ({
      name: file.split(/[\\/]/).pop(),
      text: readFileSync(file, "utf8").replace(/\r\n/g, "\n").trim(),
    }));
}
for (const pkg of metadata.packages.filter(
  (pkg) => selected.has(pkg.id) && pkg.id !== metadata.resolve.root,
)) {
  const texts = [
    ...licenses(dirname(pkg.manifest_path), pkg.license_file),
    ...licenses(join(desktop, "licenses", pkg.name + "-" + pkg.version)),
  ];
  if (!texts.length)
    missing.push({
      kind: "cargo",
      name: pkg.name,
      version: pkg.version,
      license: pkg.license,
      repository: pkg.repository,
    });
  entries.push({
    kind: "Cargo",
    name: pkg.name,
    version: pkg.version,
    license: pkg.license || "See license file",
    repository: pkg.repository || "",
    authors: pkg.authors || [],
    texts,
  });
}
const lock = JSON.parse(
  readFileSync(join(desktop, "package-lock.json"), "utf8"),
);
for (const [path, locked] of Object.entries(lock.packages)) {
  if (!path || !existsSync(join(desktop, path, "package.json"))) continue;
  const pkg = JSON.parse(
    readFileSync(join(desktop, path, "package.json"), "utf8"),
  );
  let texts = licenses(join(desktop, path));
  if (!texts.length && pkg.name === "@tauri-apps/cli-win32-x64-msvc") {
    const parent = JSON.parse(
      readFileSync(
        join(desktop, "node_modules/@tauri-apps/cli/package.json"),
        "utf8",
      ),
    );
    if (parent.version === locked.version)
      texts = licenses(join(desktop, "node_modules/@tauri-apps/cli"));
  }
  if (!texts.length && pkg.name === "@rolldown/binding-win32-x64-msvc") {
    const parent = JSON.parse(
      readFileSync(join(desktop, "node_modules/rolldown/package.json"), "utf8"),
    );
    if (parent.version === locked.version)
      texts = licenses(join(desktop, "node_modules/rolldown"));
  }
  if (!texts.length)
    missing.push({
      kind: "npm",
      name: pkg.name,
      version: locked.version,
      license: pkg.license,
    });
  entries.push({
    kind: "npm",
    name: pkg.name,
    version: locked.version,
    license: pkg.license || "See license file",
    repository:
      typeof pkg.repository === "string"
        ? pkg.repository
        : pkg.repository?.url || "",
    authors: [],
    texts,
  });
}
entries.sort(
  (a, b) =>
    a.kind.localeCompare(b.kind) ||
    a.name.localeCompare(b.name) ||
    a.version.localeCompare(b.version),
);
let output = "CaseQuarry Desktop — third-party dependency notices\n\n";
output +=
  "Exact locked Windows x64 Cargo dependencies and locally installed npm source/build dependencies.\nBuild tools are listed for source distribution transparency; not every listed dependency is included in the installed executable.\n\n";
for (const entry of entries) {
  output +=
    "=".repeat(76) +
    "\n" +
    entry.kind +
    ": " +
    entry.name +
    " " +
    entry.version +
    "\nLicense: " +
    entry.license +
    "\n";
  if (entry.repository) output += "Upstream: " + entry.repository + "\n";
  if (entry.kind === "Cargo")
    output +=
      "Unmodified covered source: https://crates.io/api/v1/crates/" +
      entry.name +
      "/" +
      entry.version +
      "/download\n";
  if (entry.authors.length)
    output += "Package author metadata: " + entry.authors.join("; ") + "\n";
  for (const text of entry.texts)
    output += "\n--- " + text.name + " ---\n" + text.text + "\n";
  output += "\n";
}
writeFileSync(join(desktop, "THIRD_PARTY_NOTICES.txt"), output);
writeFileSync(
  join(desktop, "DEPENDENCY_INVENTORY.json"),
  JSON.stringify(
    {
      platform: "windows-x64",
      scope:
        "Locked Windows Cargo graph and installed npm source/build packages; includes build tools.",
      notice_file: "THIRD_PARTY_NOTICES.txt",
      notice_sha256: createHash("sha256").update(output).digest("hex"),
      packages: entries.map((entry) => ({
        ecosystem: entry.kind,
        name: entry.name,
        version: entry.version,
        license: entry.license,
        license_files: entry.texts.map((text) => text.name),
        notice_file: "THIRD_PARTY_NOTICES.txt",
        primary_links: [
          entry.repository,
          entry.kind === "Cargo"
            ? "https://crates.io/api/v1/crates/" +
              entry.name +
              "/" +
              entry.version +
              "/download"
            : "https://www.npmjs.com/package/" +
              entry.name +
              "/v/" +
              entry.version,
        ].filter(Boolean),
      })),
    },
    null,
    2,
  ) + "\n",
);
if (missing.length) {
  writeFileSync(
    join(desktop, "../../.data/desktop-license-missing.json"),
    JSON.stringify(missing, null, 2),
  );
  console.error(
    "License text is absent from " +
      missing.length +
      " published dependency packages; review .data/desktop-license-missing.json.",
  );
  process.exitCode = 1;
} else {
  console.log(
    "Dependency notices complete: " + entries.length + " locked packages.",
  );
}
