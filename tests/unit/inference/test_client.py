"""P06: OpenAI-compatible client request shaping, thinking toggle, retries, hygiene."""

from __future__ import annotations

import logging

import httpx
import pytest

from inference.client import ChatClient, ModelCallError, extract_json
from inference.profiles import EndpointConfig

MSG = [{"role": "user", "content": "hi"}]


def _ep(**kw) -> EndpointConfig:
    base = {
        "backend": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1/",
        "model": "m",
        "retries": 2,
    }
    return EndpointConfig(**{**base, **kw})


def _client(server=None, sleeps=None, env=None, **kw) -> ChatClient:
    return ChatClient(
        _ep(**kw),
        transport=server.transport if server else None,
        env=env or {},
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )


# --- thinking toggle --------------------------------------------------------------------


def test_think_false_via_reasoning_effort_is_explicit_none():
    payload = _client(think=False, think_param="reasoning_effort").build_payload(MSG)
    assert payload["reasoning_effort"] == "none"
    assert "think" not in payload  # Ollama /v1 silently ignores a bare `think` field


@pytest.mark.parametrize("think", [True, None])
def test_think_on_or_unset_sends_no_effort_field(think):
    payload = _client(think=think, think_param="reasoning_effort").build_payload(MSG)
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize("think", [True, False])
def test_think_via_chat_template_kwargs_for_vllm(think):
    payload = _client(think=think, think_param="chat_template_kwargs").build_payload(MSG)
    assert payload["chat_template_kwargs"] == {"enable_thinking": think}
    assert "reasoning_effort" not in payload


def test_think_param_none_never_sends_a_field():
    payload = _client(think=False, think_param="none").build_payload(MSG)
    assert "reasoning_effort" not in payload and "chat_template_kwargs" not in payload


# --- structured output + generic shaping -------------------------------------------------


def test_json_schema_mode_wraps_the_schema():
    schema = {"type": "object"}
    payload = _client().build_payload(MSG, response_schema=schema, schema_name="obs")
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "obs", "schema": schema},
    }


def test_json_schema_mode_without_schema_falls_back_to_json_object():
    assert _client().build_payload(MSG)["response_format"] == {"type": "json_object"}


def test_structured_output_none_sends_no_response_format():
    payload = _client(structured_output="none").build_payload(MSG, response_schema={"a": 1})
    assert "response_format" not in payload


def test_payload_uses_profile_defaults_and_overrides():
    c = _client(max_tokens=333, temperature=0.2, extra_body={"top_p": 0.9})
    payload = c.build_payload(MSG)
    assert (payload["model"], payload["max_tokens"], payload["temperature"]) == ("m", 333, 0.2)
    assert payload["top_p"] == 0.9 and payload["stream"] is False
    payload = c.build_payload(MSG, max_tokens=50, temperature=0.0)
    assert (payload["max_tokens"], payload["temperature"]) == (50, 0.0)


def test_url_joins_chat_completions(mock_server, reply):
    server = mock_server(reply("ok"))
    seen = []
    transport = httpx.MockTransport(lambda r: (seen.append(str(r.url)), server.handler(r))[1])
    ChatClient(_ep(), transport=transport, env={}).chat(MSG)
    assert seen == ["http://127.0.0.1:11434/v1/chat/completions"]


# --- retries ----------------------------------------------------------------------------


def test_retries_5xx_with_backoff_then_succeeds(mock_server, reply):
    sleeps: list[float] = []
    server = mock_server(503, 500, reply("fine"))
    result = _client(server, sleeps).chat(MSG)
    assert result.content == "fine" and result.attempts == 3
    assert sleeps == [0.5, 1.0]


def test_empty_content_from_thinking_is_retried(mock_server, reply):
    server = mock_server(reply("", finish="length", reasoning="hmm " * 50), reply("answer"))
    result = _client(server).chat(MSG)
    assert result.content == "answer" and result.attempts == 2


def test_exhausted_retries_raise_with_attempt_count(mock_server, reply):
    server = mock_server(reply("", finish="length", reasoning="x"))
    with pytest.raises(ModelCallError, match="empty content.*thinking") as err:
        _client(server, retries=1).chat(MSG)
    assert err.value.attempts == 2 and len(server.requests) == 2


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")], ids=["timeout", "connect"]
)
def test_transport_failures_are_retried(mock_server, reply, exc):
    server = mock_server(exc, reply("ok"))
    assert _client(server).chat(MSG).attempts == 2


def test_client_4xx_fails_fast(mock_server):
    server = mock_server(404)
    with pytest.raises(ModelCallError, match="HTTP 404") as err:
        _client(server).chat(MSG)
    assert err.value.attempts == 1 and len(server.requests) == 1


def test_429_is_retried(mock_server, reply):
    server = mock_server(429, reply("ok"))
    assert _client(server).chat(MSG).attempts == 2


def test_malformed_body_is_retried(mock_server, reply):
    server = mock_server({"nope": 1}, reply("ok"))
    assert _client(server).chat(MSG).content == "ok"


# --- content handling ---------------------------------------------------------------------


def test_leaked_think_tags_are_stripped(mock_server, reply):
    server = mock_server(reply('<think>secret plan</think>\n{"a": 1}'))
    assert _client(server).chat(MSG).content == '{"a": 1}'


def test_content_parts_are_joined(mock_server):
    body = {
        "choices": [
            {"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}
        ]
    }
    assert _client(mock_server(body)).chat(MSG).content == "ab"


def test_result_records_model_usage_latency(mock_server, reply):
    result = _client(mock_server(reply("x", model="served-model"))).chat(MSG)
    assert result.model == "served-model" and result.usage["total_tokens"] == 120
    assert result.latency_s >= 0 and result.finish_reason == "stop"


# --- secrets / payload hygiene -------------------------------------------------------------


def test_api_key_header_comes_from_env_and_never_leaks(mock_server, reply, caplog):
    server = mock_server(503, reply("ok"))
    caplog.set_level(logging.DEBUG)
    c = _client(server, env={"MY_KEY": "sekret-value-123"}, api_key_env="MY_KEY")
    c.chat([{"role": "user", "content": "data:image/jpeg;base64,AAAA"}])
    assert server.headers[0]["authorization"] == "Bearer sekret-value-123"
    assert "sekret-value-123" not in caplog.text
    assert "base64" not in caplog.text


def test_no_auth_header_without_key(mock_server, reply):
    server = mock_server(reply("ok"))
    _client(server, api_key_env="MISSING_KEY").chat(MSG)
    assert "authorization" not in server.headers[0]


def test_errors_do_not_echo_the_request(mock_server):
    server = mock_server(400)
    with pytest.raises(ModelCallError) as err:
        _client(server).chat([{"role": "user", "content": "data:image/png;base64,ZZZZ"}])
    assert "ZZZZ" not in str(err.value)


def test_requires_openai_endpoint():
    with pytest.raises(ValueError):
        ChatClient(EndpointConfig(backend="fixture", fixture="x.json"))


# --- extract_json -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n[{"a": 1}]\n```', [{"a": 1}]),
        ('Sure! Here it is: {"a": {"b": [1, 2]}} hope this helps', {"a": {"b": [1, 2]}}),
        ('frames [0, 1] show {"observations": []}', {"observations": []}),
        ('<think>{"x": 0}</think>{"a": 2}', {"a": 2}),
    ],
)
def test_extract_json_tolerates_fences_and_prose(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", '{"a": ', "```json\n```"])
def test_extract_json_rejects_non_json(text):
    with pytest.raises(ValueError):
        extract_json(text)
