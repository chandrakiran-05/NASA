# Geographic selection outlines

Made with Natural Earth. The bundled `countries.json` contains 177 country features derived from the public-domain 1:110 million country dataset:

- Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
- Raw data: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
- Public-domain terms: https://www.naturalearthdata.com/about/terms-of-use/
- Retrieved: 15 November 2026.

The bundle retains name aliases, continent and geometry; coordinates are rounded to three decimal places. It is approximately 198 KB, uncompressed. This is a deliberately generalized navigation illustration, not an authoritative political boundary or a geometry for acquiring or analyzing observations. Natural Earth depicts de facto boundaries and may omit small islands/countries at this scale.

Country matching uses exact names and aliases. Continental highlights group the included country polygons and retain internal borders; they are not dissolved continent coastlines. Australia selects the country; Oceania selects the continental grouping. Cities and states are not fabricated from these country shapes: the helper returns null so the caller can use its backend geometry or a location marker.

## State and province navigation

`states.json` contains 294 first-level administrative features from Natural Earth's public-domain 1:50 million dataset, covering Australia, Brazil, Canada, China, India, Indonesia, Russia, South Africa and the United States. Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_50m_admin_1_states_provinces.geojson (retrieved 15 November 2026). Coordinates are rounded to 3 decimal places and simplified with a 0.04 degree Douglas-Peucker tolerance for display. The 656 KB asset loads only after a matching state name; it is not part of the initial globe request.

State camera positions use the source's label latitude/longitude. Country/city homonyms Georgia, New York and Delhi retain backend resolution. City search extents are outlined using the backend's labeled approximate BBox. None of these display shapes is sent to acquisition or analysis endpoints.
