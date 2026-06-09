[OPEN] Debug Session: frontend-runtime-undefined

## Symptoms
- Browser console shows: `Uncaught TypeError: Cannot read properties of undefined (reading 'length')`
- Page also shows related API/CORS noise while testing integrations.

## Hypotheses
1) A frontend component reads `.length` on an API-derived value that can be `undefined`.
2) One of the new integration mapping pickers assumes `customers`, `locations`, or `folders` is always an array.
3) Review stats/goal fetch failures leave UI state undefined and a derived render path crashes.
4) A recent response-shape change on the backend no longer matches frontend expectations.

## Evidence Needed
- Exact frontend symbol/code path reading `.length`.
- Whether the crashing value comes from review stats, clickup folders, google ads customers, or gbp locations.
- Whether the payload is `undefined`, `null`, or a non-array object.

