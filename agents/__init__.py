"""Simulerte agenter og demodata. Ingen ekte agent, ingen ekte verktoey.

- `scenarios`: ca. 40 forespoersler fra fem agenter i det oppdiktede selskapet
  Nordlys Forsikring. 90 % harmloese.
- `story`: hovedscenarioet "binance_inspired", hele kjeden paa 90 sekunder.
- `traps`: dokumenter med usynlig felle, og TrapEvent naar en felle gaar av.

Alt er deterministisk og fungerer uten internett og uten API-noekkel.
"""

from agents import scenarios, story, traps

__all__ = ["scenarios", "story", "traps"]
