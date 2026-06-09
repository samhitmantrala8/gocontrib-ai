"""Tool layer: deterministic, side-effect-tracked operations on the repo.

Tools are intentionally simple Python functions, not LangChain ``Tool`` objects.
Agents that need a ReAct loop wrap them via the schema in ``patcher.py``. This
keeps the tools usable from ordinary Python (and from tests) without dragging
in a tool-runtime."""
