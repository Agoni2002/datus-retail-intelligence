"""Offline provider fixture. Datus, the Agents SDK, and MCP remain unmocked."""

import json

from openai.types.responses import (
    Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
    ResponseUsage,
)

from retail_agents.analyst import json_object


class ScriptedTransport:
    def __init__(self, calls, respond):
        self.calls = iter(calls)
        self.respond = respond
        self.turn = 0
        self.results = {}
        self.calls_sent = {}
        self.sdk_feedback = {}

    async def stream_response(self, system_instructions, input, *args, **kwargs):
        self.turn += 1
        for item in input if isinstance(input, list) else ():
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                if item["call_id"] in self.calls_sent:
                    raw = item.get("output")
                    try:
                        feedback = json.loads(raw) if isinstance(raw, str) else raw
                    except (ValueError, TypeError):
                        feedback = None
                    name = self.calls_sent[item["call_id"]]
                    self.sdk_feedback[item["call_id"]] = (
                        isinstance(feedback, dict) and feedback.get("success") == 0
                        and feedback.get("error") == f"Tool '{name}' not found."
                    )
                output = json_object(item.get("output"))
                if output:
                    self.results[item["call_id"]] = output
        call = next(self.calls, None)
        if call is not None:
            name, arguments = call
            call_id = f"retail-call-{self.turn}"
            self.calls_sent[call_id] = name
            output = [ResponseFunctionToolCall(
                name=name, arguments=json.dumps(arguments), call_id=call_id, type="function_call",
            )]
        else:
            answer = json.dumps(self.respond(list(self.results.values())), ensure_ascii=False)
            output = [ResponseOutputMessage(
                id="retail-answer", role="assistant", status="completed", type="message",
                content=[ResponseOutputText(type="output_text", text=answer, annotations=[])],
            )]
        response = Response.model_construct(
            id=f"retail-{self.turn}", output=output, status="completed",
            usage=ResponseUsage(input_tokens=10, output_tokens=10, total_tokens=20,
                                input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
                                output_tokens_details={"reasoning_tokens": 0}),
        )
        yield ResponseCompletedEvent(type="response.completed", sequence_number=1, response=response)
