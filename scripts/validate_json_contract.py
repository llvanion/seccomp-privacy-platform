#!/usr/bin/env python3
import argparse
import json
from typing import Any, NoReturn


class ValidationError(Exception):
    pass


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def value_type_label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise ValidationError(f"unsupported schema type {expected}")


def path_join(base: str, key: str) -> str:
    if base == "$":
        return f"$.{key}"
    return f"{base}.{key}"


def validate_value(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise ValidationError(f"{path}: schema node must be an object")

    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: expected const {schema['const']!r}, got {value!r}")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list):
            raise ValidationError(f"{path}: enum must be a list")
        if value not in enum:
            raise ValidationError(f"{path}: value {value!r} is not one of {enum!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not all(isinstance(item, str) for item in allowed):
            raise ValidationError(f"{path}: type must be a string or list of strings")
        if not any(type_matches(value, item) for item in allowed):
            raise ValidationError(
                f"{path}: expected type {'/'.join(allowed)}, got {value_type_label(value)}"
            )

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValidationError(f"{path}: required must be a list")
        for key in required:
            if key not in value:
                raise ValidationError(f"{path}: missing required property {key}")

        properties = schema.get("properties", {})
        if properties is not None and not isinstance(properties, dict):
            raise ValidationError(f"{path}: properties must be an object")
        properties = properties or {}

        for key, subschema in properties.items():
            if key in value:
                validate_value(value[key], subschema, path_join(path, key))

        additional = schema.get("additionalProperties", True)
        if additional is False:
            allowed_keys = set(properties)
            extra = sorted(set(value) - allowed_keys)
            if extra:
                raise ValidationError(f"{path}: unexpected properties {extra}")
        elif isinstance(additional, dict):
            for key, item in value.items():
                if key not in properties:
                    validate_value(item, additional, path_join(path, key))
        elif additional is not True:
            raise ValidationError(f"{path}: unsupported additionalProperties value")

    if isinstance(value, list) and "items" in schema:
        items = schema["items"]
        if not isinstance(items, dict):
            raise ValidationError(f"{path}: items must be an object")
        for idx, item in enumerate(value):
            validate_value(item, items, f"{path}[{idx}]")

    if isinstance(value, str) and "minLength" in schema:
        min_length = int(schema["minLength"])
        if len(value) < min_length:
            raise ValidationError(f"{path}: string length {len(value)} is below minLength {min_length}")

    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema:
        minimum = schema["minimum"]
        if value < minimum:
            raise ValidationError(f"{path}: value {value} is below minimum {minimum}")


def validate_json_file(schema: dict[str, Any], path: str) -> int:
    validate_value(load_json(path), schema)
    return 1


def validate_jsonl_file(schema: dict[str, Any], path: str, *, first_record_only: bool = False) -> int:
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValidationError(f"line {line_no}: invalid JSON: {e}") from e
            validate_value(value, schema, f"$[line {line_no}]")
            count += 1
            if first_record_only:
                break
    if count == 0:
        raise ValidationError(f"{path}: no JSONL records found")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate JSON/JSONL files against the repo's local JSON schema subset.")
    ap.add_argument("--schema", required=True, help="Path to a JSON schema file")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json", dest="json_path", help="Path to a JSON file")
    mode.add_argument("--jsonl", dest="jsonl_path", help="Path to a JSONL file")
    mode.add_argument("--jsonl-first-record", dest="jsonl_first_record_path", help="Validate only the first JSONL record")
    args = ap.parse_args()

    schema = load_json(args.schema)
    target = args.json_path or args.jsonl_path or args.jsonl_first_record_path
    try:
        if args.json_path:
            count = validate_json_file(schema, args.json_path)
        elif args.jsonl_path:
            count = validate_jsonl_file(schema, args.jsonl_path)
        else:
            count = validate_jsonl_file(schema, args.jsonl_first_record_path, first_record_only=True)
    except ValidationError as e:
        die(f"{target}: {e}")

    print(f"[ok] schema validated: {target} ({count} record{'s' if count != 1 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
