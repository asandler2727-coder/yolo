Analyze the last 24h of crypto conversation on X. Output two sections:
1. HEATING: coins with sharply rising mention volume/enthusiasm that trade on
   Kraken vs USD — for each: pair, one-line why, links to 2-3 representative posts.
2. COOLING: coins whose hype collapsed or turned negative (rug accusations,
   exploit news, dev drama) that trade on Kraken vs USD — same format.
Be skeptical of coordinated shilling; note it when suspected. End with a JSON
array of the COOLING pairs only, e.g. ["PEPE/USD","WIF/USD"], on its own line.
Save the full analysis as sentiment/reports/<today>.md and the JSON array as
sentiment/cooling.json.
