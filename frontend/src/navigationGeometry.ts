/** Display-only boundaries. Never send these simplified shapes to a science endpoint. */
export type NavigationGeometry = {
  type: "Polygon" | "MultiPolygon";
  coordinates: number[][][] | number[][][][];
};

export type NavigationFeature = {
  names: string[];
  continent: string;
  geometry: NavigationGeometry;
};

const normalize = (value: string) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const aliases: Record<string, string> = {
  usa: "united states of america", "u s a": "united states of america", "united states": "united states of america",
  uk: "united kingdom", "u k": "united kingdom", britain: "united kingdom", "great britain": "united kingdom",
  congo: "republic of the congo", "south korea": "republic of korea", "north korea": "democratic people s republic of korea",
};

/** Exact aliases prevent partial names (Indiana/India, South Africa/Africa) colliding. */
export function selectNavigationGeometry(features: NavigationFeature[], name: string): NavigationGeometry | null {
  const query = aliases[normalize(name)] || normalize(name);
  const country = features.find(feature => feature.names.some(alias => normalize(alias) === query));
  if (country) return country.geometry;
  const continentNames = new Set(["africa", "asia", "europe", "north america", "south america", "oceania", "antarctica"]);
  if (!continentNames.has(query)) return null;
  const countries = features.filter(feature => normalize(feature.continent) === query);
  if (!countries.length) return null;
  return {
    type: "MultiPolygon",
    coordinates: countries.flatMap(feature => feature.geometry.type === "Polygon"
      ? [feature.geometry.coordinates as number[][][]]
      : feature.geometry.coordinates as number[][][][]),
  };
}

let cachedFeatures: Promise<NavigationFeature[]> | undefined;

function waitForAsset<T>(asset: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return asset;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason || new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    asset.then(value => {
      signal.removeEventListener("abort", abort);
      if (!signal.aborted) resolve(value);
    }, error => {
      signal.removeEventListener("abort", abort);
      reject(error);
    });
  });
}

/** One local asset request shared across modes; aborting one consumer leaves the cache usable. */
export async function loadNavigationGeometry(name: string, signal?: AbortSignal): Promise<NavigationGeometry | null> {
  if (!name.trim()) return null;
  signal?.throwIfAborted();
  cachedFeatures ??= fetch("/geography/countries.json").then(async response => {
    if (!response.ok) throw new Error("Navigation boundaries could not load.");
    const data: unknown = await response.json();
    if (!Array.isArray(data)) throw new Error("Navigation boundary asset is invalid.");
    return data as NavigationFeature[];
  }).catch(error => {
    cachedFeatures = undefined;
    throw error;
  });
  const features = await waitForAsset(cachedFeatures, signal);
  return selectNavigationGeometry(features, name);
}
