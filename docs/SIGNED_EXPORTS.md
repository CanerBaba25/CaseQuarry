# Signed evidence packages

CaseQuarry 0.8.0 can sign native ZIP exports and derived production ZIPs with a
dedicated operator-managed Ed25519 key. Recipients verify the manifest and every
data member against a public key they trust independently. CSV/JSON metadata
exports remain unsigned. Signing requires no provider account or network request.

## Configure the server

Create an existing protected directory outside the source repository and managed
evidence objects. Generate a new key pair using the installed CLI:

```sh
cq export signing-key-create --private-key-file /secure/keys/export-private.pem --public-key-file /secure/keys/export-public.pem
```

Use the corresponding absolute local paths on Windows. The command refuses
existing files, filesystem aliases and missing parent directories. It protects
both files before writing private material and never prints the private key.
`cq --dry-run export signing-key-create ...` previews paths without generating keys.
The supported private format is unencrypted Ed25519 PKCS8 PEM; the public format is
Ed25519 SubjectPublicKeyInfo PEM. Keep the private key readable only by the server's
authorized operating-system account and protected recovery operators.

Set `CASEQUARRY_EXPORT_SIGNING_KEY_FILE` to the absolute private-key path in the
server environment and restart the server and any external workers. A missing or
blank setting retains unsigned operation. A nonempty invalid key fails startup;
if a key becomes unavailable during processing, the ZIP job fails visibly rather
than producing an unsigned replacement. Signing does not change review, privilege,
current-access or independent production-approval requirements.

For Compose, mount the PEM read-only into both `api` and `worker` and set this
variable to the same absolute container path in both services through a private
Compose override. The host `.env` setting alone is not passed into these containers.
Allow the service account to read the mounted file; do not copy it into an image or
place it in the evidence volume. The default Compose configuration remains unsigned.

Completed ZIP records show signed/unsigned status and the signing key identifier.
An identifier is `sha256:` followed by the SHA-256 of the raw 32-byte Ed25519 public
key. This identifies a key; it does not make an unknown key trustworthy.

## Verify a received ZIP

Obtain `export-public.pem` through an independently trusted process, and confirm its
key identifier with the producer. A key delivered only alongside an unknown ZIP
does not establish the producer's identity. Then run:

```sh
cq evidence verify-package --path received.zip --trusted-public-key export-public.pem
```

Verification is offline and does not extract or modify the archive. Success
requires both a valid trusted-key signature and matching complete file inventory,
byte lengths and SHA-256 values. Duplicate ZIP/JSON entries, unsafe paths, encrypted
or linked members, altered files and missing/extra data members are rejected.
Inspect `valid` as well as `signature_valid`: an authentic manifest paired with an
altered data file can have a valid signature while the package fails verification.
Integrity failure exits with code 8.

The default total uncompressed ZIP budget is 8 GiB, including metadata. Supply an
explicit positive `--max-total-bytes` for a larger authorized package. Limits also
include 20,000 data members, a 64 MiB manifest, a 16 KiB signature document and a
32 MiB central directory. Files are hashed in bounded chunks. Budget failure is a
failed verification, never a partial success.

The existing `evidence verify-manifest` command checks an unsigned
`casequarry-hash-manifest-v1` against already extracted native files. Signed v2 ZIPs
use `verify-package` with the trusted key; neither command substitutes for human
content review or the recipient's production-platform import checks.

## Format and coverage

Signed packages contain `manifest.json` and `manifest.signature.json`. The native
schema is `casequarry-hash-manifest-v2`; the derived production schema is
`casequarry-derived-production-v2`. Unsigned packages retain their v1 schemas.

The manifest's `package_files` maps every data member's canonical ZIP path to its
`sha256` and `byte_size`. It excludes the manifest and signature themselves. Native
files are covered; production coverage includes derived documents, individual page
images, CSV/DAT load files and the OPT image map. A redacted production still
contains only approved derivatives and its documented recipient metadata.

The signature document has exactly five fields: `schema_version` set to
`casequarry-manifest-signature-v1`, `algorithm` set to `Ed25519`, `key_id`,
`manifest_sha256` and Base64 `signature`. Ed25519 signs the ASCII bytes
`CaseQuarry manifest signature v1`, followed by one NUL byte and the exact UTF-8
`manifest.json` bytes. Archive compression, member order and ZIP comments are not
authenticated container metadata; the signed manifest and listed file bytes are
the verified content.

## Rotation and recovery

Keep a protected separate recovery copy of the private key; a key outside the
configured storage root is not automatically part of an application storage
backup. Retain all independently trusted historical public keys and their key
identifiers. Generate a new pair for rotation and change the server setting;
never overwrite an earlier pair in place. Each generated package uses one key
snapshot. Earlier packages continue to verify with their earlier trusted key.

A signature establishes that the manifest was signed by the holder of the trusted
private key. It supplies no independent timestamp, collection-completeness proof,
custodian identity verification or legal chain-of-custody certification. A
compromised signing key requires an explicit trust/recovery response; a checksum
or a newly supplied public key does not undo that compromise.
