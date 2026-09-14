"""Export Elle's generated evaluation matrix as Foundry-ready JSONL."""

import json
from pathlib import Path

from anti_vanilla_evaluator import build_cases


target = Path(__file__).with_name("anti_vanilla_cases.jsonl")
target.write_text(
    "".join(json.dumps(case, separators=(",", ":")) + "\n" for case in build_cases()),
    encoding="utf-8",
)
print(f"Wrote {len(build_cases())} evaluations to {target}")

