"""Run the isolated Retail Analyst through the installed Datus custom-node runtime."""

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml
from agents import Model, set_tracing_disabled
from agents.tool import FunctionTool, ToolOriginType, get_function_tool_origin
from datus.agent.node.node import Node
from datus.configuration.agent_config_loader import load_agent_config
from datus.configuration.node_type import NodeType
from datus.schemas.gen_sql_agentic_node_models import GenSQLNodeInput

from etl.config import ROOT
from etl.snapshot import Snapshots
from retail_agents.context_index import build
from retail_agents.mcp_server import SDK_TOOLS, SERVER

DATUS_PYTHON = Path("/home/userz/Projects/Datus-agent/.venv/bin/python")
NODE = "retail_analyst"


class RestrictedToolSurface(RuntimeError):
    pass


class FencedTransport(Model):
    """Check the final SDK tool surface immediately before each provider call."""

    def __init__(self, transport, trace):
        self.transport = transport
        self.trace = trace

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def check(self, tools, handoffs):
        names = sorted(getattr(tool, "name", "") for tool in tools)
        self.trace.append(names)
        if (handoffs or len(names) != len(SDK_TOOLS) or set(names) != SDK_TOOLS or
                any(not isinstance(tool, FunctionTool) or (origin := get_function_tool_origin(tool)) is None
                    or origin.type != ToolOriginType.MCP for tool in tools)):
            raise RestrictedToolSurface(f"Retail Analyst SDK tool surface differs from its MCP allowlist: {names}")

    async def stream_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                              tracing, **kwargs):
        self.check(tools, handoffs)
        async for event in self.transport.stream_response(
            system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        ):
            yield event

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, **kwargs):
        self.check(tools, handoffs)
        return await self.transport.get_response(
            system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        )


def configure(home, snapshot, index_dir, index_id, audit, run_id, offline):
    template = ROOT / "agents/prompts/retail_analyst_system_1.0.j2"
    target = home / "template"
    target.mkdir()
    shutil.copyfile(template, target / template.name)
    config = yaml.safe_load((ROOT / "configs/retail_analyst.yml").read_text())
    agent = config["agent"]
    agent["home"] = str(home)
    agent["models"] = {"retail_provider": {
        "type": "openai", "model": os.getenv("RETAIL_MODEL", "gpt-4.1-mini") if not offline else "gpt-4.1-mini",
        "api_key": "offline-testing" if offline else "${OPENAI_API_KEY}",
        "max_retry": 1,
    }}
    agent["agentic_nodes"][NODE]["model"] = "retail_provider"
    agent["services"] = {
        "datasources": {"retail": {
            "type": "duckdb", "uri": str(snapshot), "schema": "ads", "read_only": True,
            "enable_external_access": False, "memory_limit": "256MB", "default": True,
        }},
        "mcp_servers": {SERVER: {
            "type": "stdio", "command": str(DATUS_PYTHON), "args": [
                "-B", "-m", "retail_agents.mcp_server", "--snapshot", str(snapshot),
                "--index-dir", str(index_dir), "--index-id", index_id, "--audit", str(audit),
                "--run-id", run_id,
            ],
            "env": {"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
            "tool_filter": {"allowed_tool_names": sorted(SDK_TOOLS), "enabled": True},
        }},
    }
    path = home / "agent.yml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    loaded = load_agent_config(config=str(path), datasource="retail", reload=True)
    loaded.restrict_tool_visibility = True
    loaded.workflow_permission_profile = "normal"
    return loaded


def json_object(value):
    """Extract typed JSON from Datus/MCP SDK content blocks and wrappers."""
    if isinstance(value, str):
        try:
            return json_object(json.loads(value))
        except (ValueError, TypeError):
            return None
    if isinstance(value, list):
        return next((parsed for item in value if (parsed := json_object(item)) is not None), None)
    if isinstance(value, dict):
        if ("request_id" in value and "ok" in value) or "answer" in value:
            return value
        for key in ("structuredContent", "structured_content", "text", "content", "result", "raw_output", "output",
                    "func_tool_result", "response", "tool_output", "result_data"):
            if key in value and (parsed := json_object(value[key])) is not None:
                return parsed
    return None


async def run(question, publication, runtime, transport=None, *, index_report=None, mcp_session=None):
    if transport is None and not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY to run a live Retail Analyst question")
    set_tracing_disabled(True)
    publication = Snapshots(publication)
    state = publication.latest()
    if state is None:
        raise ValueError("Publish a warehouse snapshot first")
    snapshot = publication.directory / state["database"]
    runtime = runtime.resolve()
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    index_dir = runtime / "context"
    index = index_report or build(snapshot, index_dir)
    run_id = uuid4().hex
    audit_directory = runtime / "audit"
    audit_directory.mkdir(mode=0o700, exist_ok=True)
    audit = mcp_session.audit if mcp_session else audit_directory / f"{run_id}.jsonl"
    offset = audit.stat().st_size if mcp_session and audit.exists() else 0
    trace, actions, outputs = [], [], {}
    with TemporaryDirectory(prefix="session-", dir=runtime) as temporary:
        cfg = configure(Path(temporary), snapshot, index_dir, index["index_id"], audit,
                        mcp_session.id if mcp_session else run_id,
                        transport is not None)
        node = Node.new_instance(
            node_id=NODE, description="Guarded retail analytics", node_type=NodeType.TYPE_GEN_SQL,
            input_data=GenSQLNodeInput(user_message=question, workspace_root=str(ROOT), db_schema="ads"),
            agent_config=cfg, node_name=NODE, execution_mode="workflow", is_subagent=True,
        )
        if mcp_session:
            node.mcp_servers = await mcp_session.borrow(node.mcp_servers, state["version"])
        model = node.model
        node.model = model
        # The provider can inject hosted tools independently of native
        # permission filtering. Disable those capabilities on this node's model.
        web_search, web_fetch = model.supports_builtin_web_search, model.supports_builtin_web_fetch
        model.supports_builtin_web_search = lambda: False
        model.supports_builtin_web_fetch = lambda: False
        adapter = model.litellm_adapter
        provider = adapter.get_agents_sdk_model
        adapter.get_agents_sdk_model = lambda: FencedTransport(transport if transport is not None else provider(), trace)
        try:
            async for action in node.execute_stream():
                if str(action.role).upper() != "TOOL":
                    continue
                name = action.action_type
                if name not in SDK_TOOLS:
                    continue
                data = json_object(action.output)
                actions.append({"tool": name, "status": str(action.status),
                                "request_id": data.get("request_id") if data else None})
                if data:
                    outputs[data["request_id"]] = data
        finally:
            adapter.get_agents_sdk_model = provider
            model.supports_builtin_web_search = web_search
            model.supports_builtin_web_fetch = web_fetch
        result = node.result
        answer = json_object(result.response) if result and result.success else None
        session = getattr(node, "_session", None)
        if session is not None and hasattr(session, "close"):
            session.close()
    events = []
    if audit.exists():
        with audit.open("rb") as stream:
            stream.seek(offset)
            events = [json.loads(line) for line in stream]
    return {"run_id": run_id, "snapshot_version": state["version"], "index_id": index["index_id"],
            "answer": answer, "tool_surface": trace, "actions": actions, "audit": events, "tool_outputs": outputs}


def answer_is_grounded(result):
    answer = result["answer"]
    if not answer or not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
        return False
    evidence = answer.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    metrics, limitations = answer.get("metric_ids"), answer.get("limitations")
    known = yaml.safe_load((ROOT / "metrics/definitions.yml").read_text())["metrics"]
    if (not isinstance(metrics, list) or not metrics or
            any(not isinstance(metric, str) or metric not in known for metric in metrics) or
            not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations)):
        return False
    executed = {event["request_id"] for event in result["audit"]
                if event["outcome"] == "allowed" and event["tool"] in {"retail_query", "retail_metric"}
                and event["snapshot_version"] == result["snapshot_version"]}
    completed = {action["request_id"] for action in result["actions"] if action["status"] == "success"}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("request_id"), str):
            return False
        request = item["request_id"]
        if request not in executed or request not in completed:
            return False
        actual = result["tool_outputs"].get(request, {})
        if not actual.get("ok") or any(key not in actual or item.get(key) != actual[key] for key in ("columns", "rows")):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/fixture")
    parser.add_argument("--runtime", type=Path, default=ROOT / ".datus-runtime/retail-analyst")
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        result = asyncio.run(run(args.question, args.output, args.runtime))
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    if not answer_is_grounded(result):
        parser.exit(1, "The analyst did not return an answer supported by its guarded tool results.\n")
    print(json.dumps({"run_id": result["run_id"], **result["answer"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
