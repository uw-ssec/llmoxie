"""Make data/reader.py and data/group_sessions.py importable as top-level modules.

They live in data/ rather than src/llmaven/ and import each other with plain
`from reader import ...`, matching how they're run in practice
(`python data/group_sessions.py ...`, or `%autoreload` in data/analysis.ipynb).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
