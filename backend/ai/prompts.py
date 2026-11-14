"""Prompts for the local model. Short, explicit, and grounded: the model only rephrases facts we give it."""

SYSTEM_BASE = (
    "You are the assistant inside 'Earth System Trend Detective', a NASA Space Apps tool for high-school and "
    "college students. You ONLY discuss Earth-system data (land, atmosphere, ocean, water, ice, air quality), "
    "NASA/NOAA datasets, and the statistics used to detect trends (regression slope, t-test, Mann-Kendall, "
    "Sen's slope, confidence intervals, seasonality, autocorrelation). If asked anything else, reply exactly: "
    "OFF_TOPIC. Use simple words and short sentences. Never invent numbers, dates, places or dataset names: "
    "use only those in the CONTEXT. If the context does not contain the answer, say what is missing."
)

PLAN_INSTRUCTIONS = (
    "Turn the student's question into an investigation plan. Choose 1-3 variable ids ONLY from the list in "
    "CONTEXT. If the question names a place, copy the place name exactly; do not invent coordinates unless "
    "the place is well known, and then give its approximate centre. Years must be between 1980 and {max_year}. "
    "If the question does not specify years, return null for them."
)

EXPLAIN_INSTRUCTIONS = (
    "Write a short explanation (110-170 words) of this trend analysis for a high-school student. Start with the "
    "main finding (direction and rate per decade with units), then say whether it is statistically significant "
    "and what that means in everyday words, then mention up to two extra insights (trend breaks, time of "
    "emergence, years needed to detect, robustness, projection) if present, then the most important caveat. "
    "Use ONLY numbers that appear in FACTS (you may round them). Do not speculate about causes beyond the "
    "'possible_processes' field. Do not use headings or bullet points."
)

ASK_INSTRUCTIONS = (
    "Answer the student's question in 60-140 words using the CONTEXT (variable definitions and region "
    "suggestions from the tool's catalog). Recommend which variables to investigate and why. Use only numbers "
    "found in CONTEXT. End with one suggested investigation the student can run in the tool."
)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "variable_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "place_name": {"type": ["string", "null"]},
        "approx_lat": {"type": ["number", "null"]},
        "approx_lon": {"type": ["number", "null"]},
        "region_type": {"type": ["string", "null"]},
        "start_year": {"type": ["integer", "null"]},
        "end_year": {"type": ["integer", "null"]},
        "wants_forecast": {"type": "boolean"},
        "wants_compare": {"type": "boolean"},
        "compare_places": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["variable_ids", "place_name", "approx_lat", "approx_lon", "region_type", "start_year",
                 "end_year", "wants_forecast", "wants_compare", "compare_places"],
    "additionalProperties": False,
}
