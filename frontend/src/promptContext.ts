export type PromptTopic =
  "earth" | "temperature" | "rainfall" | "vegetation" | "weather";

export type PromptContext = {
  topic: PromptTopic;
  placeQuery: string | null;
  /** Approximate navigation aid only. Never submit this as scientific geometry. */
  navigationFocus?: { lat: number; lon: number; name: string };
};

// A small navigation vocabulary, not a geographic database. Countries, states and
// cities still go through the backend region service before acquiring any data.
const places: Array<{ name: string; aliases: string[] }> = [
  { name: "Tamil Nadu", aliases: ["tamil nadu", "tamilnadu"] },
  { name: "South Africa", aliases: ["south africa"] },
  {
    name: "United States",
    aliases: ["united states of america", "united states", "usa", "u.s.a."],
  },
  { name: "United Kingdom", aliases: ["united kingdom", "uk"] },
  ...[
    "India",
    "Brazil",
    "Canada",
    "China",
    "Japan",
    "France",
    "Germany",
    "Kenya",
    "Nigeria",
    "Indonesia",
    "Pakistan",
    "Bangladesh",
    "Sri Lanka",
    "Nepal",
    "Mexico",
    "California",
    "Texas",
    "Indiana",
    "Kerala",
    "Karnataka",
    "Maharashtra",
    "Rajasthan",
    "Gujarat",
    "West Bengal",
    "Chennai",
    "Mumbai",
    "New Delhi",
    "Delhi",
    "Hyderabad",
    "Kolkata",
    "Pune",
    "London",
    "New York",
    "Tokyo",
    "Paris",
    "Nairobi",
    "Sydney",
    "Melbourne",
  ].map((name) => ({ name, aliases: [name.toLowerCase()] })),
  { name: "Bengaluru", aliases: ["bengaluru", "bangalore"] },
];

// Rounded continent/region centers are camera targets, not boundaries, measured
// data, observations or a substitute for backend region validation.
const navigationPlaces = [
  { name: "Africa", lat: 2, lon: 20, aliases: ["africa"] },
  { name: "Asia", lat: 34, lon: 90, aliases: ["asia"] },
  { name: "Europe", lat: 54, lon: 15, aliases: ["europe"] },
  { name: "North America", lat: 45, lon: -100, aliases: ["north america"] },
  { name: "South America", lat: -15, lon: -60, aliases: ["south america"] },
  { name: "Australia", lat: -25, lon: 134, aliases: ["australia"] },
  { name: "Oceania", lat: -20, lon: 150, aliases: ["oceania"] },
  {
    name: "Antarctica",
    lat: -85,
    lon: 0,
    aliases: ["antarctica", "antarctic"],
  },
  { name: "Arctic", lat: 82, lon: 0, aliases: ["arctic"] },
];

const topicRules: Array<[PromptTopic, RegExp]> = [
  [
    "rainfall",
    /\b(?:rain|rains|rainy|rainfall|precipitation|monsoon|flood|flooding)\b/i,
  ],
  [
    "temperature",
    /\b(?:heat|hot|hotter|hottest|temperature|temperatures|warming|warmer|warm|cooling|colder|cold)\b/i,
  ],
  [
    "vegetation",
    /\b(?:vegetation|ndvi|evi|forest|forests|greenness|greenery|plant|plants|deforestation)\b/i,
  ],
  ["weather", /\b(?:weather|wind|winds|humidity|storm|storms|climate)\b/i],
];

function findAlias(
  text: string,
  aliases: string[],
): { index: number; length: number } | null {
  let best: { index: number; length: number } | null = null;
  for (const alias of aliases) {
    const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = new RegExp(
      `(^|[^\\p{L}\\p{N}])(${escaped})(?=$|[^\\p{L}\\p{N}])`,
      "iu",
    ).exec(text);
    if (!match) continue;
    const candidate = {
      index: match.index + match[1].length,
      length: match[2].length,
    };
    if (
      !best ||
      candidate.index < best.index ||
      (candidate.index === best.index && candidate.length > best.length)
    )
      best = candidate;
  }
  return best;
}

function genericPlace(question: string): string | null {
  const match = /\b(?:in|at|near|from)\s+(.+)/i.exec(question);
  if (!match) return null;
  const candidate = match[1]
    .split(
      /\b(?:since|between|during|from|to|over|for|today|yesterday|tomorrow|now|this|last|next|rain(?:fall)?|temperature(?:s)?|weather|heat|warming|vegetation|trends?|changed?|changing|getting|is|was|has|have)\b|[?!.;,\n]|\d/i,
    )[0]
    .replace(/^(?:the\s+)/i, "")
    .replace(/[\s\-–—:]+$/g, "")
    .trim();
  if (!candidate || candidate.length > 80 || candidate.split(/\s+/).length > 7)
    return null;
  if (
    /^(?:me|here|there|earth|world|data|a|an|our|my|your|climate|precipitation|wind|humidity|forest|forests|ndvi|evi|warming|cooling|hot|cold|year|years|decade|decades|month|months|the last)$/i.test(
      candidate,
    )
  )
    return null;
  if (!/^[\p{L}\p{M}][\p{L}\p{M}\s'’–-]*$/u.test(candidate)) return null;
  return candidate;
}

/** Interprets visual/navigation intent only; never computes scientific values. */
export function inferPromptContext(question: string): PromptContext {
  const topic =
    topicRules.find(([, rule]) => rule.test(question))?.[0] ?? "earth";
  const known = [
    ...places.map((place) => ({
      ...findAlias(question, place.aliases),
      place,
      navigation: undefined,
    })),
    ...navigationPlaces.map((navigation) => ({
      ...findAlias(question, navigation.aliases),
      place: undefined,
      navigation,
    })),
  ]
    .filter(
      (match): match is typeof match & { index: number; length: number } =>
        match.index !== undefined,
    )
    .sort((a, b) => a.index - b.index || b.length - a.length)[0];
  if (known?.place) return { topic, placeQuery: known.place.name };
  if (known?.navigation) {
    const { name, lat, lon } = known.navigation;
    return { topic, placeQuery: null, navigationFocus: { name, lat, lon } };
  }
  return { topic, placeQuery: genericPlace(question) };
}
