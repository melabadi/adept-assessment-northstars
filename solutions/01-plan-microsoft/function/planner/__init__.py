"""The Plan · Microsoft run in plain Python: no Azure Functions import, so the unit tests in ../../tests run anywhere.

  brief.py    what the run writes to GitHub: the review Issue, the epic, the tasks, and the comments
  checks.py   the evaluation's gates and score rows
  clients.py  Microsoft Foundry and GitHub over HTTPS (standard library only)
  store.py    one JSON record per run: in memory for the tests, in a private blob container in Azure
  steps.py    the run itself: start, draft, evaluate, check the review Issues, publish, cancel

function_app.py (one folder up) wires these to the three functions Azure runs.
"""
