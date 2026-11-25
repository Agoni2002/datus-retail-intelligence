"""Run live inference through the existing guarded Datus node."""

import asyncio
import json
import sys
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from retail_agents.analyst import answer_is_grounded, run

ROOT = Path(__file__).resolve().parents[2]


class Budget:
    input_limit = 40_000
    output_limit = 1_000

    def __init__(self):
        self.reserved_input = 0
        self.reserved_output = 0
        self.input = self.output = self.calls = self.completed = 0

    def settings(self, instructions, inputs, settings, tools):
        schema = [{"name": tool.name, "description": tool.description, "schema": tool.params_json_schema}
                  for tool in tools]
        # UTF-8 bytes bound the number of text tokens. Allow framing overhead
        # on each provider request and limit the total across all tool rounds.
        size = len(json.dumps([instructions, inputs, schema], ensure_ascii=False, default=str).encode()) + 4096
        if self.calls >= 5 or self.reserved_input + size > self.input_limit or self.reserved_output >= self.output_limit:
            raise RuntimeError("Inference budget exhausted")
        self.reserved_input += size
        self.calls += 1
        maximum = min(350, self.output_limit - self.reserved_output)
        self.reserved_output += maximum
        return replace(settings, max_tokens=maximum)

    def record(self, usage):
        if usage is not None:
            self.input += int(getattr(usage, "input_tokens", 0) or 0)
            self.output += int(getattr(usage, "output_tokens", 0) or 0)
            self.completed += 1

    def report(self):
        return {"input": self.input, "output": self.output,
                "complete": self.calls > 0 and self.completed == self.calls}


async def main(payload):
    publication = ROOT / "data/processed/olist"
    budget = Budget()
    with redirect_stdout(sys.stderr):
        result = await run(payload["question"], publication, ROOT / "deployment/.runtime/live-agent",
                           inference_budget=budget, expected_snapshot=payload["snapshot"])
    verified = result["snapshot_version"] == payload["snapshot"] and answer_is_grounded(result)
    answer = result["answer"] if verified else None
    if answer:
        evidence = []
        for item in answer["evidence"]:
            output = result["tool_outputs"][item["request_id"]]
            evidence.append({key: output[key] for key in ("columns", "rows", "sql") if key in output})
        answer = {"answer": answer["answer"], "evidence": evidence,
                  "metric_ids": answer["metric_ids"], "limitations": answer["limitations"]}
    print(json.dumps({"answer": answer, "usage": budget.report()}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(json.load(sys.stdin)))
