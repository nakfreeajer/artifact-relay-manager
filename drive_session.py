"""Windows-user DPAPI storage for one Google Drive refresh token."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

MAGIC = b"ARMS1"
MAX_SESSION_BYTES = 65536
SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class SessionStoreError(Exception):
    """Sanitized protected-session storage failure."""


class Protector(Protocol):
    def protect(self, plaintext: bytes, entropy: bytes) -> bytes: ...
    def unprotect(self, ciphertext: bytes, entropy: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsDpapi:
    """Current-user CryptProtectData wrapper with UI disabled."""

    UI_FORBIDDEN = 0x1

    def __init__(self):
        if os.name != "nt":
            raise SessionStoreError("protected Drive sessions require Windows DPAPI")
        self.crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self.crypt32.CryptProtectData.restype = wintypes.BOOL
        self.crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self.crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel32.LocalFree.restype = ctypes.c_void_p

    def _call(self, function, data: bytes, entropy: bytes, *, protect: bool) -> bytes:
        source, source_buffer = _blob(data)
        optional_entropy, entropy_buffer = _blob(entropy)
        output = _DataBlob()
        description = wintypes.LPWSTR()
        try:
            if protect:
                ok = function(
                    ctypes.byref(source), "Artifact Relay Google Drive session", ctypes.byref(optional_entropy),
                    None, None, self.UI_FORBIDDEN, ctypes.byref(output),
                )
            else:
                ok = function(
                    ctypes.byref(source), ctypes.byref(description), ctypes.byref(optional_entropy),
                    None, None, self.UI_FORBIDDEN, ctypes.byref(output),
                )
            if not ok:
                raise SessionStoreError("Windows DPAPI operation failed")
            return ctypes.string_at(output.pbData, output.cbData)
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("Windows DPAPI operation failed") from None
        finally:
            # Keep API input buffers live through the call and wipe DPAPI's output buffer.
            _ = source_buffer, entropy_buffer
            if output.pbData:
                ctypes.memset(output.pbData, 0, output.cbData)
                self.kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
            if description:
                self.kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))

    def protect(self, plaintext: bytes, entropy: bytes) -> bytes:
        return self._call(self.crypt32.CryptProtectData, plaintext, entropy, protect=True)

    def unprotect(self, ciphertext: bytes, entropy: bytes) -> bytes:
        return self._call(self.crypt32.CryptUnprotectData, ciphertext, entropy, protect=False)


PROTECTOR_FACTORY = WindowsDpapi


class DriveSessionStore:
    """Deterministic, client/scope-bound protected refresh-token file."""

    def __init__(self, client_id: str, scope: str = SCOPE, *, protector: Protector | None = None,
                 local_app_data: str | Path | None = None):
        if not isinstance(client_id, str) or not client_id or not isinstance(scope, str) or not scope:
            raise SessionStoreError("invalid Drive session identity")
        root_value = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA")
        if not root_value:
            raise SessionStoreError("LOCALAPPDATA is unavailable")
        self.client_id = client_id
        self.scope = scope
        self.entropy = hashlib.sha256(
            b"ArtifactRelayManager\0GoogleDrive\0" + client_id.encode("utf-8") + b"\0" + scope.encode("utf-8")
        ).digest()
        identity = hashlib.sha256(client_id.encode("utf-8") + b"\0" + scope.encode("utf-8")).hexdigest()
        self.path = Path(root_value) / "ArtifactRelayManager" / "GoogleDrive" / ("session-" + identity + ".dpapi")
        self._protector = protector

    @property
    def protector(self) -> Protector:
        if self._protector is None:
            self._protector = PROTECTOR_FACTORY()
        return self._protector

    def ensure_protector(self) -> None:
        _ = self.protector

    def load_refresh_token(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open("rb") as stream:
                stored = stream.read(MAX_SESSION_BYTES + 1)
            if len(stored) > MAX_SESSION_BYTES or not stored.startswith(MAGIC) or len(stored) == len(MAGIC):
                raise SessionStoreError("protected Drive session is invalid")
            plaintext = self.protector.unprotect(stored[len(MAGIC):], self.entropy)
            record = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_unique_pairs)
            if (not isinstance(record, dict) or set(record) != {"schemaVersion", "refreshToken"}
                    or type(record.get("schemaVersion")) is not int or record["schemaVersion"] != 1
                    or not isinstance(record.get("refreshToken"), str)
                    or not record["refreshToken"] or len(record["refreshToken"]) > 16384):
                raise SessionStoreError("protected Drive session is invalid")
            return record["refreshToken"]
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("protected Drive session is invalid or cannot be decrypted") from None

    def save_refresh_token(self, refresh_token: str) -> None:
        if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 16384:
            raise SessionStoreError("invalid Drive refresh token")
        try:
            plaintext = json.dumps(
                {"schemaVersion": 1, "refreshToken": refresh_token}, separators=(",", ":")
            ).encode("utf-8")
            stored = MAGIC + self.protector.protect(plaintext, self.entropy)
            if len(stored) > MAX_SESSION_BYTES:
                raise SessionStoreError("protected Drive session exceeds its size limit")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(stored)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("could not persist protected Drive session") from None

    def delete(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            raise SessionStoreError("could not reset protected Drive session") from None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate protected-session JSON key")
        result[key] = value
    return result
