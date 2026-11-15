import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { FormEvent } from "react";
import { ApiError } from "./api";
import { twinApi } from "./twinApi";
import type {
  Twin,
  TwinKnobs,
  TwinSimulation,
  TwinSimulationVariable,
} from "./twinApi";

export interface TwinLabHandle {
  submitPrompt: (question: string) => void;
}
export interface TwinLabProps {
  active: boolean;
  place?: string;
  importSeriesId?: string;
  onBusyChange?: (busy: boolean) => void;
}

function CurveChart({
  curve,
  name,
}: {
  curve: TwinSimulationVariable;
  name: string;
}) {
  const width = 800,
    height = 310,
    left = 66,
    right = 24,
    top = 24,
    bottom = 42;
  const values = [
    ...curve.p05,
    ...curve.p95,
    ...(curve.reference?.p05 ?? []),
    ...(curve.reference?.p95 ?? []),
  ].filter(Number.isFinite);
  if (!values.length || !curve.time.length)
    return <p>No simulation values were returned.</p>;
  let low = Math.min(...values),
    high = Math.max(...values);
  if (low === high) {
    low -= 1;
    high += 1;
  }
  const padding = (high - low) * 0.08;
  low -= padding;
  high += padding;
  const x = (i: number) =>
    left + (i / Math.max(curve.time.length - 1, 1)) * (width - left - right);
  const y = (v: number) =>
    top + ((high - v) / (high - low)) * (height - top - bottom);
  function line(data: number[]) {
    let pen = false;
    return data
      .map((v, i) => {
        if (!Number.isFinite(v)) {
          pen = false;
          return "";
        }
        const part = `${pen ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`;
        pen = true;
        return part;
      })
      .join(" ");
  }
  const bands: string[] = [];
  let segment: number[] = [];
  const finish = () => {
    if (segment.length)
      bands.push(
        `${segment.map((i, j) => `${j ? "L" : "M"}${x(i)},${y(curve.p05[i])}`).join(" ")} ${segment
          .slice()
          .reverse()
          .map((i) => `L${x(i)},${y(curve.p95[i])}`)
          .join(" ")} Z`,
      );
    segment = [];
  };
  curve.time.forEach((_, i) => {
    if (Number.isFinite(curve.p05[i]) && Number.isFinite(curve.p95[i]))
      segment.push(i);
    else finish();
  });
  finish();
  return (
    <div className="twin-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${name}: simulated median with 5th–95th percentile band${curve.reference ? " and a simulated reference without scenario changes" : ""}. ${curve.time[0]} to ${curve.time.at(-1)}. Units ${curve.baseline.units ?? "not supplied"}.`}
      >
        {[0, 0.5, 1].map((t) => {
          const value = low + (high - low) * t;
          return (
            <g key={t}>
              <line
                x1={left}
                x2={width - right}
                y1={y(value)}
                y2={y(value)}
                stroke="currentColor"
                opacity=".13"
              />
              <text
                x={left - 10}
                y={y(value) + 4}
                fill="currentColor"
                textAnchor="end"
                fontSize="12"
              >
                {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </text>
            </g>
          );
        })}
        {bands.map((d, i) => (
          <path key={i} d={d} fill="#f5b773" opacity=".16" />
        ))}
        {curve.reference && (
          <path
            d={line(curve.reference.p50)}
            fill="none"
            stroke="#c2d7e5"
            strokeWidth="2"
            strokeDasharray="6 5"
          />
        )}
        <path
          d={line(curve.p50)}
          fill="none"
          stroke="#f5b773"
          strokeWidth="2.5"
        />
        <text x={left} y={height - 12} fill="currentColor" fontSize="12">
          {curve.time[0]}
        </text>
        <text
          x={width - right}
          y={height - 12}
          fill="currentColor"
          fontSize="12"
          textAnchor="end"
        >
          {curve.time.at(-1)}
        </text>
        <text x={left} y={14} fill="currentColor" fontSize="12">
          {curve.baseline.units ?? "Units not supplied"}
        </text>
      </svg>
      <div className="twin-legend">
        <span>— Simulated scenario median</span>
        <span>Shaded: simulated 5th–95th percentiles</span>
        {curve.reference && <span>┄ Simulated reference, no changes</span>}
      </div>
      <details>
        <summary>Read simulated values</summary>
        <div className="twin-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">5th percentile</th>
                <th scope="col">Median</th>
                <th scope="col">95th percentile</th>
              </tr>
            </thead>
            <tbody>
              {curve.time.map((date, i) => (
                <tr key={`${date}-${i}`}>
                  <th scope="row">{date}</th>
                  <td>{curve.p05[i]}</td>
                  <td>{curve.p50[i]}</td>
                  <td>{curve.p95[i]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

const TwinLab = forwardRef<TwinLabHandle, TwinLabProps>(function TwinLab(
  { active, place, importSeriesId, onBusyChange },
  ref,
) {
  const [twins, setTwins] = useState<Twin[]>([]);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [name, setName] = useState("");
  const [variable, setVariable] = useState("");
  const [horizon, setHorizon] = useState("30");
  const [multiplier, setMultiplier] = useState("1");
  const [addition, setAddition] = useState("0");
  const [threshold, setThreshold] = useState("");
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [result, setResult] = useState<TwinSimulation | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const section = useRef<HTMLElement>(null);
  const inflight = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const selected = useRef<string | null>(null);
  const busyCallback = useRef(onBusyChange);
  busyCallback.current = onBusyChange;

  useImperativeHandle(
    ref,
    () => ({
      submitPrompt(question) {
        setPrompt(question.trim().slice(0, 2000));
        window.requestAnimationFrame(() =>
          section.current?.scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? "auto"
              : "smooth",
            block: "start",
          }),
        );
      },
    }),
    [],
  );

  function markBusy(value: boolean) {
    setBusy(value);
    busyCallback.current?.(value);
  }
  function stop() {
    generation.current++;
    inflight.current?.abort();
    inflight.current = null;
    markBusy(false);
  }
  async function perform<T>(
    operation: (signal: AbortSignal) => Promise<T>,
    apply: (data: T) => void,
  ) {
    inflight.current?.abort();
    const controller = new AbortController();
    const token = ++generation.current;
    inflight.current = controller;
    setError("");
    markBusy(true);
    try {
      const data = await operation(controller.signal);
      if (token === generation.current && !controller.signal.aborted) {
        setUnavailable(false);
        apply(data);
      }
    } catch (e) {
      if (token === generation.current && !controller.signal.aborted) {
        if (e instanceof ApiError && e.status === 404) setUnavailable(true);
        else
          setError(
            e instanceof Error
              ? e.message
              : "The twin request could not finish.",
          );
      }
    } finally {
      if (token === generation.current) {
        inflight.current = null;
        markBusy(false);
      }
    }
  }
  function adopt(next: Twin) {
    selected.current = next.id;
    setTwin(next);
    setVariable((current) =>
      next.variables.some((v) => v.name === current)
        ? current
        : (next.variables[0]?.name ?? ""),
    );
    setTwins((current) => [...current.filter((t) => t.id !== next.id), next]);
  }
  function load() {
    void perform(
      async (signal) => {
        const list = await twinApi.list(signal);
        const chosen =
          selected.current && list.twins.some((t) => t.id === selected.current)
            ? selected.current
            : null;
        return {
          list,
          detail: chosen ? await twinApi.get(chosen, signal) : null,
        };
      },
      ({ list, detail }) => {
        setTwins(list.twins);
        if (detail) adopt(detail);
      },
    );
  }
  useEffect(() => {
    if (active) load();
    else stop();
    return () => {
      generation.current++;
      inflight.current?.abort();
      inflight.current = null;
      busyCallback.current?.(false);
    };
  }, [active]);
  useEffect(() => {
    setMultiplier("1");
    setAddition("0");
    setThreshold("");
    setDirection("above");
  }, [twin?.id, variable]);

  function create(event: FormEvent) {
    event.preventDefault();
    void perform(
      (signal) =>
        twinApi.create(
          name,
          place ? `Scenario workspace for ${place}` : undefined,
          signal,
        ),
      (next) => {
        setResult(null);
        adopt(next);
        setName("");
      },
    );
  }
  function choose(id: string) {
    stop();
    setError("");
    setResult(null);
    selected.current = id || null;
    if (!id) {
      setTwin(null);
      setVariable("");
      return;
    }
    void perform((signal) => twinApi.get(id, signal), adopt);
  }
  async function refreshAfter(
    operation: (signal: AbortSignal) => Promise<Twin>,
    signal: AbortSignal,
  ) {
    const changed = await operation(signal);
    return twinApi.get(changed.id, signal);
  }
  function upload(file: File | undefined) {
    if (!file || !twin) return;
    const id = twin.id;
    void perform(
      (signal) => refreshAfter((s) => twinApi.uploadCSV(id, file, s), signal),
      (next) => {
        setResult(null);
        adopt(next);
        setFileKey((k) => k + 1);
      },
    );
  }
  function importObserved() {
    if (!twin || !importSeriesId) return;
    const id = twin.id;
    void perform(
      (signal) =>
        refreshAfter(
          (s) => twinApi.importSeries(id, importSeriesId, s),
          signal,
        ),
      (next) => {
        setResult(null);
        adopt(next);
      },
    );
  }
  function simulate(event: FormEvent) {
    event.preventDefault();
    if (!twin || !variable) return;
    const knobs: TwinKnobs = {
      trend_multiplier: Number(multiplier),
      trend_add_per_decade: Number(addition),
    };
    if (threshold.trim())
      knobs.threshold = { value: Number(threshold), direction };
    setResult(null);
    void perform(
      (signal) =>
        twinApi.simulate(
          twin.id,
          {
            horizon_years: Number(horizon),
            n_runs: 500,
            seed: 2026,
            compare_to_baseline: true,
            scenario: { [variable]: knobs },
          },
          signal,
        ),
      setResult,
    );
  }
  const chosenVariable = twin?.variables.find((v) => v.name === variable);
  const baseline =
    chosenVariable?.baseline && !("error" in chosenVariable.baseline)
      ? chosenVariable.baseline
      : null;
  const curve = result?.variables[variable];
  const finalDelta = curve?.reference ? curve.delta_p50?.at(-1) : undefined;
  const units = chosenVariable?.units || "variable units";

  return (
    <section
      className="twin-lab"
      ref={section}
      aria-labelledby="twin-title"
      aria-busy={busy}
    >
      <div className="twin-toolbar">
        <div>
          <h2 id="twin-title">
            Test a different future.
          </h2>
          <p>
            Bring a record, set a scenario, and compare simulated outcomes with
            a reference that keeps the fitted trend.
          </p>
        </div>
        <span className="twin-badge">Engineer sandbox</span>
      </div>
      {place && (
        <p className="twin-place">
          Place in view: {place}. Twin data defines the simulation.
        </p>
      )}
      {prompt && (
        <div className="twin-notice">
          <strong>Your question</strong>
          <p>{prompt}</p>
          <p>
            Set the assumptions below to test it. Your words have not been
            converted into scenario settings.
          </p>
        </div>
      )}
      <p className="twin-notice">
        Research uploads enter this sandbox directly. They do not pass the
        verified-trend checks. Simulations are not observations or climate
        projections.
      </p>
      {unavailable ? (
        <div className="twin-notice" role="status">
          <h3>The twin service is not available on this backend.</h3>
          <p>
            The DigiTwin module exists on the backend-active-trends branch. This
            server did not expose the requested twin resource. No substitute
            simulation has been generated.
          </p>
          <button type="button" onClick={load} disabled={busy}>
            Check twin service
          </button>
        </div>
      ) : (
        <>
          <fieldset className="twin-controls" disabled={busy}>
            <legend className="sr-only">Digital twin workspace</legend>
            <div className="twin-toolbar">
              <label className="twin-field">
                Open a twin
                <select
                  value={twin?.id ?? ""}
                  onChange={(event) => choose(event.target.value)}
                >
                  <option value="">Choose a saved twin</option>
                  {twins.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <form className="twin-create" onSubmit={create}>
                <label className="twin-field">
                  Create a twin
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Chennai heat study"
                    required
                    maxLength={120}
                  />
                </label>
                <button type="submit">Create twin</button>
              </form>
            </div>
            {twin && (
              <>
                <div className="twin-uploads">
                  <label className="twin-field">
                    Upload research CSV
                    <input
                      key={fileKey}
                      type="file"
                      accept=".csv,text/csv"
                      onChange={(event) => upload(event.target.files?.[0])}
                    />
                    <small>
                      Date column first, then numeric variables. Maximum 20 MB;
                      at least 24 valid observations per variable to simulate.
                    </small>
                  </label>
                  {importSeriesId && (
                    <button type="button" onClick={importObserved}>
                      Copy current observed series
                    </button>
                  )}
                </div>
                <p className="twin-note">
                  A copy leaves the original record unchanged. Re-uploading a
                  variable name replaces its data in this twin.
                </p>
                {twin.variables.length > 0 ? (
                  <form className="twin-form" onSubmit={simulate}>
                    <label className="twin-field">
                      Variable
                      <select
                        value={variable}
                        onChange={(event) => setVariable(event.target.value)}
                        required
                      >
                        {twin.variables.map((v) => (
                          <option key={v.name} value={v.name}>
                            {v.name}
                            {v.units ? ` (${v.units})` : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="twin-field">
                      Years after last observation
                      <input
                        type="number"
                        min="1"
                        max="100"
                        step="1"
                        required
                        value={horizon}
                        onChange={(event) => setHorizon(event.target.value)}
                      />
                    </label>
                    <label className="twin-field">
                      Trend multiplier
                      <input
                        type="number"
                        step="any"
                        required
                        value={multiplier}
                        onChange={(event) => setMultiplier(event.target.value)}
                      />
                      <small>1 keeps the fitted rate; 2 doubles it.</small>
                    </label>
                    <label className="twin-field">
                      Added rate ({units}/decade)
                      <input
                        type="number"
                        step="any"
                        required
                        value={addition}
                        onChange={(event) => setAddition(event.target.value)}
                      />
                    </label>
                    <label className="twin-field">
                      Threshold ({units}, optional)
                      <input
                        type="number"
                        step="any"
                        value={threshold}
                        onChange={(event) => setThreshold(event.target.value)}
                        placeholder="No threshold"
                      />
                    </label>
                    <label className="twin-field">
                      Crossing direction
                      <select
                        value={direction}
                        onChange={(event) =>
                          setDirection(event.target.value as "above" | "below")
                        }
                        disabled={!threshold.trim()}
                      >
                        <option value="above">At or above</option>
                        <option value="below">At or below</option>
                      </select>
                    </label>
                    {baseline && (
                      <p className="twin-summary">
                        Fitted rate:{" "}
                        {baseline.slope_per_decade.toLocaleString(undefined, {
                          maximumSignificantDigits: 4,
                        })}{" "}
                        {units}/decade. Last observation:{" "}
                        {baseline.last_observed}. Record: {baseline.frequency};{" "}
                        {baseline.n_valid} valid observations.
                      </p>
                    )}
                    {chosenVariable?.baseline &&
                      "error" in chosenVariable.baseline && (
                        <p className="twin-notice">
                          {chosenVariable.baseline.error}
                        </p>
                      )}
                    <div className="twin-actions">
                      <button
                        type="submit"
                        disabled={
                          !variable ||
                          !!(
                            chosenVariable?.baseline &&
                            "error" in chosenVariable.baseline
                          )
                        }
                      >
                        Run scenario
                      </button>
                      <span>
                        500 simulated runs · fixed seed 2026 · reference
                        included
                      </span>
                    </div>
                  </form>
                ) : (
                  <p className="twin-notice">
                    This twin is empty. Upload a CSV or copy a historical series
                    to fit a baseline.
                  </p>
                )}
              </>
            )}
          </fieldset>
        </>
      )}
      {busy && (
        <div className="twin-actions" role="status">
          <p>Working with the twin service…</p>
          <button type="button" onClick={stop}>
            Stop waiting
          </button>
          <small>
            Stops browser waiting; a server operation already received may still
            finish.
          </small>
        </div>
      )}
      {error && (
        <p className="twin-error" role="alert">
          {error}
        </p>
      )}
      {result && curve && (
        <article className="twin-result" aria-labelledby="twin-result-title">
          <div className="section-label">SIMULATED / {result.n_runs} RUNS</div>
          <h3 id="twin-result-title">{variable}: scenario against reference</h3>
          <p className="twin-summary">
            Run settings: trend × {curve.scenario.trend_multiplier ?? 1}; added
            rate {curve.scenario.trend_add_per_decade ?? 0}{" "}
            {curve.baseline.units ?? "units"}/decade. {result.horizon_years}{" "}
            years after {curve.baseline.last_observed}; seed {result.seed}.
          </p>
          {finalDelta !== undefined && Number.isFinite(finalDelta) && (
            <p className="twin-summary">
              Simulated median difference from reference at {curve.time.at(-1)}:{" "}
              {finalDelta > 0 ? "+" : ""}
              {finalDelta.toLocaleString(undefined, {
                maximumSignificantDigits: 4,
              })}{" "}
              {curve.baseline.units ?? "(units not supplied)"}.
            </p>
          )}
          <p className="twin-notice">{result.disclaimer}</p>
          <CurveChart curve={curve} name={variable} />
          {curve.threshold && (
            <div className="twin-threshold">
              <h4>User-defined threshold crossing</h4>
              <p>{curve.threshold.plain_language}</p>
              <p>
                Median first crossing among runs that cross:{" "}
                {curve.threshold.median_first_crossing ?? "No runs crossed"}.
                This is a scenario level, not a detected tipping point.
              </p>
              <details>
                <summary>Read cumulative crossing probabilities</summary>
                <ul>
                  {curve.threshold.probability_by_year.map((row) => (
                    <li key={row.year}>
                      {row.year}:{" "}
                      {(row.p * 100).toLocaleString(undefined, {
                        maximumFractionDigits: 1,
                      })}
                      % of simulated runs
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </article>
      )}
    </section>
  );
});

export default TwinLab;
