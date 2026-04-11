# -*- coding:utf-8 _*-
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


STORE_SCHEMA = "sse_encrypted_record_store/v1"
KDF_NAME = "PBKDF2HMAC-SHA256"
AEAD_NAME = "AES-256-GCM"
KDF_ITERATIONS = 390000
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32


def build_record_store(*,
                       rows: Iterable[dict],
                       out_path: Path,
                       record_id_field: str,
                       key_env: str) -> int:
    if not record_id_field:
        raise ValueError("record_id_field is required")

    passphrase = _read_key_env(key_env)
    salt = os.urandom(SALT_SIZE)
    key = _derive_key(passphrase, salt, KDF_ITERATIONS)
    aead = AESGCM(key)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        header = {
            "schema": STORE_SCHEMA,
            "kdf": KDF_NAME,
            "kdf_salt_b64": _b64e(salt),
            "kdf_iterations": KDF_ITERATIONS,
            "aead": AEAD_NAME,
            "record_id_field": record_id_field,
        }
        f.write(json.dumps(header, ensure_ascii=False) + "\n")

        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("each source record must be a JSON object")
            record_id_value = row.get(record_id_field)
            if record_id_value in (None, ""):
                continue
            record_id = _stringify_record_id(record_id_value)
            record_id_tag = _record_id_tag(key, record_id)
            plaintext = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            nonce = os.urandom(NONCE_SIZE)
            ciphertext = aead.encrypt(nonce, plaintext, _aad(record_id_tag))
            f.write(json.dumps({
                "record_id_tag": record_id_tag,
                "nonce_b64": _b64e(nonce),
                "ciphertext_b64": _b64e(ciphertext),
            }, ensure_ascii=False) + "\n")
            count += 1
    return count


def load_candidate_rows(*,
                        store_path: Path,
                        key_env: str,
                        candidate_ids: set[str]) -> list[dict]:
    return list(iter_candidate_rows(
        store_path=store_path,
        key_env=key_env,
        candidate_ids=candidate_ids,
    ))


def iter_candidate_rows(*,
                        store_path: Path,
                        key_env: str,
                        candidate_ids: set[str]):
    if candidate_ids is None:
        raise ValueError("candidate_ids is required")

    passphrase = _read_key_env(key_env)
    with store_path.open("r", encoding="utf-8") as f:
        header_line = f.readline()
        if not header_line:
            raise ValueError("encrypted record store is empty")
        header = json.loads(header_line)
        _validate_header(header)
        key = _derive_key(
            passphrase,
            _b64d(header["kdf_salt_b64"]),
            int(header["kdf_iterations"]),
        )
        aead = AESGCM(key)
        candidate_tags = {_record_id_tag(key, candidate_id) for candidate_id in candidate_ids}

        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            record_id_tag = _stringify_record_id(entry.get("record_id_tag", ""))
            if record_id_tag not in candidate_tags:
                continue
            plaintext = aead.decrypt(
                _b64d(entry["nonce_b64"]),
                _b64d(entry["ciphertext_b64"]),
                _aad(record_id_tag),
            )
            row = json.loads(plaintext.decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("decrypted record must be a JSON object")
            yield row


def _read_key_env(key_env: str) -> bytes:
    if not key_env:
        raise ValueError("record store key env is required")
    value = os.environ.get(key_env)
    if not value:
        raise ValueError(f"environment variable {key_env} is not set")
    return value.encode("utf-8")


def _derive_key(passphrase: bytes, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase)


def _validate_header(header: dict) -> None:
    if header.get("schema") != STORE_SCHEMA:
        raise ValueError(f"unsupported encrypted record store schema: {header.get('schema')}")
    if header.get("kdf") != KDF_NAME:
        raise ValueError(f"unsupported encrypted record store kdf: {header.get('kdf')}")
    if header.get("aead") != AEAD_NAME:
        raise ValueError(f"unsupported encrypted record store aead: {header.get('aead')}")


def _aad(record_id: str) -> bytes:
    return f"{STORE_SCHEMA}\n{record_id}".encode("utf-8")


def _record_id_tag(key: bytes, record_id: str) -> str:
    return hmac.new(key, record_id.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _stringify_record_id(value) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return str(value)
