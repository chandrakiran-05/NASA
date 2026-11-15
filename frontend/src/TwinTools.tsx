import { useEffect, useState } from "react";
import { twinApi } from "./twinApi";
import type {
  Twin,
  TwinBacktest,
  TwinCompound,
  TwinCondition,
  TwinScenario,
  TwinScenarioSet,
  TwinSensitivity,
} from "./twinApi";

const COLORS = ["#f5b773", "#c2d7e5", "#b8d39a", "#e39bb6", "#d9c27a", "#9fc6c0"];
const pct = (p: number) =>
  `${(p * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
const num = (v: number) =>
  v.toLocaleString(undefined, { maximumSignificantDigits: 4 });

export interface Line {
  label: string;
  values: (number | null)[];
  dashed?: boolean;
}

/** Plain SVG line chart: x is an index into `x`, gaps (non-finite) break the line. */
export function LineChart({
  x,
  lines,
  title,
  unit,
  percent,
}: {
  x: (string | number)[];
  lines: Line[];
  title: string;
  unit?: string | null;
  percent?: boolean;
}) {
  const width = 800,
    height = 240,
    left = 66,
    right = 24,
    top = 24,
    bottom = 36;
  const all = lines
    .flatMap((l) => l.values)
    .filter((v): v is number => Number.isFinite(v));
  if (!all.length || !x.length) return <p>No simulated values were returned.</p>;
  let low = percent ? 0 : Math.min(...all),
    high = percent ? 1 : Math.max(...all);
  if (low === high) {
    low -= 1;
    high += 1;
  }
  if (!percent) {
    const pad = (high - low) * 0.08;
    low -= pad;
    high += pad;
  }
  const px = (i: number) =>
    left + (i / Math.max(x.length - 1, 1)) * (width - left - right);
  const py = (v: number) =>
    top + ((high - v) / (high - low)) * (height - top - bottom);
  const d = (values: (number | null)[]) => {
    let pen = false;
    return values
      .map((v, i) => {
        if (v === null || !Number.isFinite(v)) {
          pen = false;
          return "";
        }
        const part = `${pen ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`;
        pen = true;
        return part;
      })
      .join(" ");
  };
  return (
    <div className="twin-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}. Simulated. ${lines.map((l) => l.label).join(", ")}; ${x[0]} to ${x.at(-1)}.`}
      >
        {[0, 0.5, 1].map((t) => {
          const v = low + (high - low) * t;
          return (
            <g key={t}>
              <line x1={left} x2={width - right} y1={py(v)} y2={py(v)} stroke="currentColor" opacity=".13" />
              <text x={left - 10} y={py(v) + 4} fill="currentColor" textAnchor="end" fontSize="12">
                {percent ? pct(v) : num(v)}
              </text>
            </g>
          );
        })}
        {lines.map((l, i) => (
          <path
            key={l.label}
            d={d(l.values)}
            fill="none"
            stroke={COLORS[i % COLORS.length]}
            strokeWidth="2.2"
            strokeDasharray={l.dashed ? "6 5" : undefined}
          />
        ))}
        <text x={left} y={height - 10} fill="currentColor" fontSize="12">{x[0]}</text>
        <text x={width - right} y={height - 10} fill="currentColor" fontSize="12" textAnchor="end">{x.at(-1)}</text>
        <text x={left} y={14} fill="currentColor" fontSize="12">
          {percent ? "Share of simulated runs" : (unit ?? "Units not supplied")}
        </text>
      </svg>
      <div className="twin-legend">
        {lines.map((l, i) => (
          <span key={l.label} style={{ color: COLORS[i % COLORS.length] }}>
            {l.dashed ? "┄" : "—"} {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ProbabilityCurve({
  rows,
  title,
  lines,
}: {
  rows: { year: number; p: number }[];
  title: string;
  lines?: Line[];
}) {
  return (
    <>
      <LineChart
        x={rows.map((r) => r.year)}
        lines={lines ?? [{ label: `${title} (simulated)`, values: rows.map((r) => r.p) }]}
        title={title}
        percent
      />
      <details>
        <summary>Read simulated probabilities by year</summary>
        <ul>
          {rows.map((r) => (
            <li key={r.year}>
              {r.year}: {pct(r.p)} of simulated runs
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

type Perform = <T>(
  operation: (signal: AbortSignal) => Promise<T>,
  apply: (data: T) => void,
) => void;

export function TwinTools({
  twin,
  variable,
  scenario,
  horizon,
  perform,
}: {
  twin: Twin;
  variable: string;
  /** Current form knobs, keyed by variable (the target variable only). */
  scenario: () => TwinScenario;
  horizon: () => number;
  perform: Perform;
}) {
  const [holdout, setHoldout] = useState("10");
  const [backtest, setBacktest] = useState<TwinBacktest | null>(null);
  const [multipliers, setMultipliers] = useState({ low: "0.5", mid: "1", high: "2" });
  const [set, setSet] = useState<TwinScenarioSet | null>(null);
  const [conditions, setConditions] = useState<
    { variable: string; value: string; direction: "above" | "below" }[]
  >([]);
  const [compound, setCompound] = useState<TwinCompound | null>(null);
  const [sensitivity, setSensitivity] = useState<TwinSensitivity | null>(null);
  useEffect(() => {
    setBacktest(null);
    setSet(null);
    setCompound(null);
    setSensitivity(null);
    setConditions(twin.variables.slice(0, 2).map((v) => ({ variable: v.name, value: "", direction: "above" })));
  }, [twin]);

  const run = { horizon_years: horizon(), n_runs: 500, seed: 2026 };
  const runBacktest = () =>
    perform(
      (s) => twinApi.backtest(twin.id, { holdout_years: Number(holdout), n_runs: 300, seed: 2026 }, s),
      setBacktest,
    );
  const runScenarios = () => {
    const base = scenario()[variable] ?? {};
    perform(
      (s) =>
        twinApi.scenarios(
          twin.id,
          {
            ...run,
            scenarios: Object.fromEntries(
              Object.entries(multipliers).map(([label, m]) => [
                label,
                { [variable]: { ...base, trend_multiplier: Number(m) } },
              ]),
            ),
          },
          s,
        ),
      setSet,
    );
  };
  const runCompound = () =>
    perform(
      (s) =>
        twinApi.compound(
          twin.id,
          {
            ...run,
            scenario: scenario(),
            conditions: conditions.map(
              (c): TwinCondition => ({
                variable: c.variable,
                value: c.value.trim() ? Number(c.value) : NaN,
                direction: c.direction,
              }),
            ),
          },
          s,
        ),
      setCompound,
    );
  const runSensitivity = () =>
    perform(
      (s) => twinApi.sensitivity(twin.id, { ...run, n_runs: 300, target: variable, scenario: scenario() }, s),
      setSensitivity,
    );

  const setLabels = set ? Object.keys(set.scenarios) : [];
  const firstCurve = set ? set.scenarios[setLabels[0]]?.[variable] : undefined;

  return (
    <div className="twin-tools">
      <section className="twin-tool" aria-labelledby="twin-backtest-title">
        <h4 id="twin-backtest-title">How trustworthy are these bands?</h4>
        <p className="twin-note">
          Hide the last years, simulate them from the earlier record, and count how many real
          observations land inside the simulated 5th–95th band (target about 90%).
        </p>
        <div className="twin-actions">
          <label className="twin-field">
            Years to hide
            <input type="number" min="2" max="40" step="1" value={holdout} onChange={(e) => setHoldout(e.target.value)} />
          </label>
          <button type="button" onClick={runBacktest}>Run backtest</button>
        </div>
        {backtest && (
          <>
            <div className="twin-table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Variable</th>
                    <th scope="col">Band coverage</th>
                    <th scope="col">Target</th>
                    <th scope="col">Median abs. error</th>
                    <th scope="col">Hidden period</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(backtest.variables).map(([name, v]) => (
                    <tr key={name}>
                      <th scope="row">{name}</th>
                      {v.status === "no_overlap" || v.band_coverage === undefined ? (
                        <td colSpan={4}>No real observations overlap the hidden period.</td>
                      ) : (
                        <>
                          <td>{pct(v.band_coverage)} of {v.months_scored} months</td>
                          <td>{pct(v.target_coverage ?? 0.9)}</td>
                          <td>{num(v.median_abs_error ?? NaN)} {v.units ?? ""}</td>
                          <td>{v.held_out?.join(" to ")}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {Object.entries(backtest.variables).map(
              ([name, v]) => v.plain_language && <p key={name}>{name}: {v.plain_language}</p>,
            )}
            <p className="twin-notice">{backtest.limit}</p>
          </>
        )}
      </section>

      <section className="twin-tool" aria-labelledby="twin-scenarios-title">
        <h4 id="twin-scenarios-title">Low / mid / high side by side</h4>
        <p className="twin-note">
          Same seed for all three, other settings from the form above: the curves differ only by the trend multiplier.
        </p>
        <div className="twin-actions">
          {(["low", "mid", "high"] as const).map((k) => (
            <label className="twin-field" key={k}>
              {k} × trend
              <input
                type="number"
                step="any"
                value={multipliers[k]}
                onChange={(e) => setMultipliers((m) => ({ ...m, [k]: e.target.value }))}
              />
            </label>
          ))}
          <button type="button" onClick={runScenarios}>Compare scenarios</button>
        </div>
        {set && firstCurve && (
          <>
            <LineChart
              x={firstCurve.time}
              title={`${variable}: simulated median per scenario`}
              unit={twin.variables.find((v) => v.name === variable)?.units}
              lines={setLabels.map((label) => ({
                label: `${label} (simulated median)`,
                values: set.scenarios[label][variable]?.p50 ?? [],
              }))}
            />
            {setLabels.map((label) => {
              const th = set.scenarios[label][variable]?.threshold;
              return th ? <p key={label}>{label}: {th.plain_language}</p> : null;
            })}
            <p className="twin-notice">{set.disclaimer}</p>
          </>
        )}
      </section>

      <section className="twin-tool" aria-labelledby="twin-compound-title">
        <h4 id="twin-compound-title">Compound tipping: all conditions in the same year</h4>
        {conditions.map((c, i) => (
          <div className="twin-actions" key={i}>
            <label className="twin-field">
              Variable
              <select
                value={c.variable}
                onChange={(e) =>
                  setConditions((all) => all.map((x, j) => (j === i ? { ...x, variable: e.target.value } : x)))
                }
              >
                {twin.variables.map((v) => (
                  <option key={v.name} value={v.name}>{v.name}</option>
                ))}
              </select>
            </label>
            <label className="twin-field">
              Direction
              <select
                value={c.direction}
                onChange={(e) =>
                  setConditions((all) =>
                    all.map((x, j) => (j === i ? { ...x, direction: e.target.value as "above" | "below" } : x)),
                  )
                }
              >
                <option value="above">At or above</option>
                <option value="below">At or below</option>
              </select>
            </label>
            <label className="twin-field">
              Level
              <input
                type="number"
                step="any"
                value={c.value}
                onChange={(e) =>
                  setConditions((all) => all.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
              />
            </label>
            <button
              type="button"
              className="text-button"
              onClick={() => setConditions((all) => all.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        <div className="twin-actions">
          {conditions.length < 5 && (
            <button
              type="button"
              className="text-button"
              onClick={() =>
                setConditions((all) => [...all, { variable: twin.variables[0]?.name ?? "", value: "", direction: "above" }])
              }
            >
              Add condition
            </button>
          )}
          <button type="button" onClick={runCompound} disabled={!conditions.length}>
            Run compound check
          </button>
        </div>
        {compound && (
          <>
            <p>{compound.plain_language}</p>
            <ProbabilityCurve
              rows={compound.probability_same_year}
              title="Share of simulated runs with all conditions met in that year"
            />
            <ul>
              {compound.conditions.map((c, i) => (
                <li key={i}>
                  {c.variable} {c.direction === "above" ? "≥" : "≤"} {c.value} alone: {pct(c.probability_by_end)} of
                  simulated runs by the end
                </li>
              ))}
            </ul>
            <p className="twin-notice">{compound.disclaimer}</p>
          </>
        )}
      </section>

      <section className="twin-tool" aria-labelledby="twin-sensitivity-title">
        <h4 id="twin-sensitivity-title">Which knob matters most for {variable}?</h4>
        <p className="twin-note">
          Needs a threshold above. Removes one setting at a time (same seed) and ranks by how much the
          simulated crossing probability moves.
        </p>
        <button type="button" onClick={runSensitivity}>Rank knobs</button>
        {sensitivity && (
          <>
            <p>
              With all settings: {pct(sensitivity.probability_with_all_knobs)} of simulated runs cross by the end.
            </p>
            <div className="twin-table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Rank</th>
                    <th scope="col">Setting</th>
                    <th scope="col">Value</th>
                    <th scope="col">Without it</th>
                    <th scope="col">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {sensitivity.ranking.map((r, i) => (
                    <tr key={`${r.variable}-${r.knob}-${r.item}`}>
                      <th scope="row">{i + 1}</th>
                      <td>{r.variable}: {r.knob}{r.item !== null ? ` #${r.item + 1}` : ""}</td>
                      <td>{JSON.stringify(r.setting)}</td>
                      <td>{pct(r.probability_without)}</td>
                      <td>{r.change > 0 ? "+" : ""}{pct(r.change)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="twin-notice">{sensitivity.note}</p>
            <p className="twin-notice">{sensitivity.disclaimer}</p>
          </>
        )}
      </section>
    </div>
  );
}
