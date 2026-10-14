import { uiText } from "@/lib/i18n";

export default function ManifestSigningStatus({
  state,
  counts,
  detail = false,
}: {
  state: string;
  counts?: Record<string, unknown>;
  detail?: boolean;
}) {
  if (state.toLowerCase() !== "completed") return null;
  const metadata = counts?.manifest_signing;
  const value =
    metadata && typeof metadata === "object"
      ? (metadata as {
          signed?: unknown;
          algorithm?: unknown;
          key_id?: unknown;
        })
      : null;
  const signed =
    value?.signed === true &&
    value.algorithm === "Ed25519" &&
    typeof value.key_id === "string" &&
    /^sha256:[a-f0-9]{64}$/.test(value.key_id);
  return (
    <div className="field-help">
      <strong>
        {signed ? uiText("Signed manifest") : uiText("Unsigned manifest")}
      </strong>
      {signed && (
        <>
          <span> · Ed25519</span>
          <code className="hash-block">{value.key_id as string}</code>
        </>
      )}
      {detail && (
        <p>
          {uiText(
            "Verify signatures against an independently trusted public key. A signature does not replace review or approval.",
          )}
        </p>
      )}
    </div>
  );
}
