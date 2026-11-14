const narrativeKeys = new Set([
  "plain_language",
  "reason",
  "message",
  "disclaimer",
  "limits",
  "limit",
  "caveats",
  "assumptions",
  "notes",
  "reasons",
  "explanation",
]);
/** Render server-authored explanations as text, never model-supplied HTML. */
export default function Narrative({ value }: { value: unknown }) {
  if (value == null || value === "") return null;
  if (Array.isArray(value))
    return (
      <>
        {value.map((item, i) => (
          <Narrative key={i} value={item} />
        ))}
      </>
    );
  if (typeof value === "object")
    return (
      <>
        {Object.entries(value)
          .filter(
            ([key, v]) =>
              narrativeKeys.has(key) ||
              (v !== null &&
                typeof v === "object" &&
                (!Array.isArray(v) ||
                  v.some(
                    (x) => x && typeof x === "object" && !Array.isArray(x),
                  ))),
          )
          .map(([key, v]) => (
            <Narrative key={key} value={v} />
          ))}
      </>
    );
  return <p>{String(value)}</p>;
}
