# Field Cases

This directory contains Scenario tests that reproduce specific real-world lab failures as reproducible regression tests.

## The Field Case Rule

Every lab failure must have:
1. Its Diagnostic log `TRIP` line quoted directly in the scenario test's docstring.
2. An end-to-end scenario test that reproduces the failure under realistic simulated conditions and guards against regression.
