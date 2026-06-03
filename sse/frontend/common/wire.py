# -*- coding:utf-8 _*-
"""JSON WebSocket wire codec for the legacy SSE frontend.

The frontend API transports opaque scheme bytes, so JSON messages encode bytes
with an explicit base64 marker instead of using Python pickle on network input.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any


WIRE_SCHEMA = "sse.frontend.ws/v1"
_TYPE_KEY = "__sse_wire_type__"
_BYTES_TYPE = "bytes"
_DATA_KEY = "base64"


class WireProtocolError(ValueError):
    """Raised when a WebSocket frame does not match the JSON wire contract."""


def _reject_json_constant(value: str) -> None:
    raise WireProtocolError(f"unsupported JSON numeric constant: {value}")


def _encode_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            _TYPE_KEY: _BYTES_TYPE,
            _DATA_KEY: base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported wire value type: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {_TYPE_KEY, _DATA_KEY} and value.get(_TYPE_KEY) == _BYTES_TYPE:
            encoded = value[_DATA_KEY]
            if not isinstance(encoded, str):
                raise WireProtocolError("bytes marker must contain base64 text")
            try:
                return base64.b64decode(encoded.encode("ascii"), validate=True)
            except (binascii.Error, UnicodeEncodeError) as exc:
                raise WireProtocolError("invalid base64 bytes marker") from exc
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


def dumps_message(message: dict[str, Any]) -> str:
    if not isinstance(message, dict):
        raise TypeError("wire message must be a dict")
    envelope = {
        "schema": WIRE_SCHEMA,
        "payload": _encode_value(message),
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def loads_message(raw_message: str | bytes) -> dict[str, Any]:
    if isinstance(raw_message, bytes):
        try:
            raw_message = raw_message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WireProtocolError("wire message bytes must be UTF-8 JSON") from exc
    if not isinstance(raw_message, str):
        raise WireProtocolError("wire message must be text or bytes")
    try:
        envelope = json.loads(raw_message, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise WireProtocolError("wire message must be valid JSON") from exc
    if not isinstance(envelope, dict):
        raise WireProtocolError("wire envelope must be a JSON object")
    if envelope.get("schema") != WIRE_SCHEMA:
        raise WireProtocolError("unsupported wire schema")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise WireProtocolError("wire payload must be a JSON object")
    return _decode_value(payload)


def encode_content(content: Any) -> bytes:
    encoded = _encode_value(content)
    return json.dumps(encoded, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")


def decode_content(content: bytes | str) -> Any:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WireProtocolError("structured content bytes must be UTF-8 JSON") from exc
    if not isinstance(content, str):
        raise WireProtocolError("structured content must be text or bytes")
    try:
        encoded = json.loads(content, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise WireProtocolError("structured content must be valid JSON") from exc
    return _decode_value(encoded)
