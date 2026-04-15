"""Local encrypted session storage utilities."""

from __future__ import annotations

import asyncio
import base64
import getpass
import hashlib
import json
import logging
import os
import re
import socket
from pathlib import Path
from typing import Dict, List


logger = logging.getLogger(__name__)


class SessionManager:
    """
    Handles storage and retrieval of session cookies.
    """

    def __init__(self, storage_path: str | None = None):
        base_storage_path = (
            Path(storage_path)
            if storage_path
            else Path(__file__).resolve().parents[3] / "data" / "sessions"
        )
        self.storage_path = base_storage_path.resolve()
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def get_session_path(self, account_id: str) -> str:
        """Return the absolute session file path for one account."""

        return str(self._get_file_path(account_id))

    def session_exists(self, account_id: str) -> bool:
        """Return whether a session file already exists for one account."""

        return self._get_file_path(account_id).exists()

    async def ensure_session_from_env(
        self,
        account_id: str,
        encoded_session_json: str | None,
    ) -> int:
        """Write a session file from an encoded environment payload when missing."""

        from app.config import decode_session_json

        path = self._get_file_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            logger.info(
                "Runtime session file already exists",
                extra={"account_id": account_id, "path": str(path)},
            )
            return 0

        cookies = decode_session_json(encoded_session_json)
        if not cookies:
            logger.info(
                "No runtime session payload provided for bootstrap",
                extra={"account_id": account_id, "path": str(path)},
            )
            return 0

        await self.store_session(account_id, cookies)
        logger.info(
            "Runtime session file created from SESSION_JSON",
            extra={
                "account_id": account_id,
                "path": str(path),
                "cookie_count": len(cookies),
            },
        )
        return len(cookies)

    def _get_file_path(self, account_id: str) -> Path:
        normalized_account_id = self._normalize_account_id(account_id)
        return self.storage_path / f"{normalized_account_id}.json"

    async def store_session(self, account_id: str, cookies: List[Dict]) -> None:
        """
        Store session cookies.
        """

        path = self._get_file_path(account_id)
        try:
            payload = self._encrypt_cookies(account_id, cookies)
            await asyncio.to_thread(self._write_payload, path, payload)
            logger.info(
                "Stored encrypted session cookies",
                extra={
                    "account_id": account_id,
                    "path": str(path),
                    "cookie_count": len(cookies),
                },
            )
        except Exception:
            logger.exception(
                "Failed to store encrypted session cookies",
                extra={"account_id": account_id, "path": str(path)},
            )
            raise

    async def get_session(self, account_id: str) -> List[Dict]:
        """
        Retrieve session cookies.
        """

        path = self._get_file_path(account_id)
        logger.info(
            "Attempting to load session cookies",
            extra={"account_id": account_id, "path": str(path)},
        )
        if not path.exists():
            logger.warning(
                "Session file not found",
                extra={"account_id": account_id, "path": str(path)},
            )
            return []

        try:
            payload = await asyncio.to_thread(self._read_payload, path)
            cookies = self._decrypt_cookies(account_id, payload)
            if cookies:
                logger.info(
                    "Loaded encrypted session cookies",
                    extra={
                        "account_id": account_id,
                        "path": str(path),
                        "cookie_count": len(cookies),
                    },
                )
            else:
                logger.warning(
                    "Session file loaded but contained no cookies",
                    extra={"account_id": account_id, "path": str(path)},
                )
            return cookies
        except Exception:
            logger.exception(
                "Failed to load encrypted session cookies",
                extra={"account_id": account_id, "path": str(path)},
            )
            return []

    async def rotate_session(self, account_id: str, new_cookies: List[Dict]) -> None:
        """
        Replace old session with new one.
        """

        try:
            await self.store_session(account_id, new_cookies)
            logger.info("Rotated session cookies", extra={"account_id": account_id})
        except Exception:
            logger.exception("Failed to rotate session", extra={"account_id": account_id})
            raise

    def _encrypt_cookies(self, account_id: str, cookies: List[Dict]) -> Dict[str, str | int]:
        """Encrypt cookie payload for local storage."""

        plaintext = json.dumps(cookies, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(16)
        key = self._derive_key(account_id)
        keystream = self._build_keystream(key, nonce, len(plaintext))
        ciphertext = self._xor_bytes(plaintext, keystream)

        return {
            "version": 1,
            "nonce": self._encode_bytes(nonce),
            "ciphertext": self._encode_bytes(ciphertext),
        }

    def _decrypt_cookies(self, account_id: str, payload: Dict | List[Dict]) -> List[Dict]:
        """Decrypt stored cookie payload."""

        if isinstance(payload, list):
            logger.warning(
                "Loaded unencrypted legacy session payload",
                extra={"account_id": account_id},
            )
            return payload

        nonce_value = payload.get("nonce")
        ciphertext_value = payload.get("ciphertext")
        if not isinstance(nonce_value, str) or not isinstance(ciphertext_value, str):
            logger.error("Invalid encrypted session payload", extra={"account_id": account_id})
            return []

        nonce = self._decode_bytes(nonce_value)
        ciphertext = self._decode_bytes(ciphertext_value)
        key = self._derive_key(account_id)
        keystream = self._build_keystream(key, nonce, len(ciphertext))
        plaintext = self._xor_bytes(ciphertext, keystream)

        try:
            loaded = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.exception("Failed to decode decrypted session payload", extra={"account_id": account_id})
            return []

        return loaded if isinstance(loaded, list) else []

    def _derive_key(self, account_id: str) -> bytes:
        """Derive a stable per-account encryption key."""

        secret_seed = os.environ.get("SESSION_MANAGER_SECRET")
        if not secret_seed:
            secret_seed = f"{getpass.getuser()}:{socket.gethostname()}"

        return hashlib.pbkdf2_hmac(
            "sha256",
            secret_seed.encode("utf-8"),
            account_id.encode("utf-8"),
            200_000,
            dklen=32,
        )

    def _build_keystream(self, key: bytes, nonce: bytes, length: int) -> bytes:
        """Build a deterministic keystream for XOR encryption."""

        stream = bytearray()
        counter = 0
        while len(stream) < length:
            counter_bytes = counter.to_bytes(4, byteorder="big", signed=False)
            stream.extend(hashlib.sha256(key + nonce + counter_bytes).digest())
            counter += 1
        return bytes(stream[:length])

    def _xor_bytes(self, left: bytes, right: bytes) -> bytes:
        """XOR two byte strings."""

        return bytes(left_byte ^ right_byte for left_byte, right_byte in zip(left, right))

    def _encode_bytes(self, value: bytes) -> str:
        """Encode bytes into a filesystem-safe text representation."""

        return base64.urlsafe_b64encode(value).decode("utf-8")

    def _decode_bytes(self, value: str) -> bytes:
        """Decode previously encoded bytes."""

        return base64.urlsafe_b64decode(value.encode("utf-8"))

    def _write_payload(self, path: Path, payload: Dict[str, str | int]) -> None:
        """Write encrypted payload to disk."""

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle)

    def _read_payload(self, path: Path) -> Dict | List[Dict]:
        """Read encrypted payload from disk."""

        with open(path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def _normalize_account_id(self, account_id: str) -> str:
        """Normalize an account id into a filesystem-safe filename segment."""

        sanitized_account_id = re.sub(r"[^A-Za-z0-9._-]", "_", account_id.strip())
        return sanitized_account_id or "default"
