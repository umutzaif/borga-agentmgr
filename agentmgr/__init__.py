"""agentmgr - coordination layer for multi-agent project handoff.

A project keeps its coordination state in a single ``.agentmgr/`` directory.
Every actor (agent, manager, human) communicates by appending one file per
event to ``.agentmgr/events/``; ``ledger.jsonl`` is a derived, hash-chained
mirror of that directory and can be rebuilt at any time.
"""

__version__ = "0.2.1"
