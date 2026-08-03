"""Offline eval harness (#342, MATURITY-ROADMAP Tier 0.1).

`python -m evals run` scores the retrieval and grounding suites against FROZEN datasets
built from the live 832-video corpus, and `--check` fails on a regression past the
committed baseline. See evals/scoring.py for what the numbers can and cannot prove.
"""
