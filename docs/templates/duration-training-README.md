# Duration training sheet — for Tim

This is the intake for the 20-30 RoofR reports you're labeling with real job durations, so we
can train a model that predicts demo/dry-in/install days from a job's roof type and measurements
instead of guessing off a flat per-square rate. One row per **phase** per house — so a typical
house is 2-3 rows (demo, dry_in, install), and if a house could be quoted in more than one roof
type (e.g. you'd bid it tile or shingle depending on what the customer picks), give it a full row
set for **each** roof type you'd actually quote, not just what was installed. Pull the measurement
columns (squares, eaves/hips/ridges/valleys/rakes/wall_flashings, stories) straight off the RoofR
report so they line up with what the estimator already sees.

`notes_why` is the most important column — it's your reasoning, not a summary. Don't write "took
longer because of complexity"; write the actual thing that moved the number, the way you'd explain
it to Josh or Marco: "hips + valleys ate a full day beyond the flat rate," "single crew but no
dumpster access added a half day to demo," "simple gable so crew size didn't matter here." That's
the logic we're trying to get the model to learn, so the more those notes vary in *why* a job ran
fast or slow — pitch, access, layer count, complexity, crew size, weather — the better it can
separate real drivers from noise. Aim for real spread across easy and hard cuts on purpose, not
just your typical job twice.
