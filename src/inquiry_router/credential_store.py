from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsCredentialStore:
    """Stores one secret encrypted for the current Windows user via DPAPI."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, secret: str) -> None:
        if not secret:
            raise ValueError("应用专用密码不能为空")
        if not hasattr(ctypes, "windll"):
            raise OSError("密码安全存储仅支持 Windows")

        source, source_buffer = _blob(secret.encode("utf-8"))
        output = DATA_BLOB()
        success = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source),
            "GenFollower Zoho password",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise ctypes.WinError()
        try:
            encrypted = ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(base64.b64encode(encrypted))
        temporary.replace(self.path)

    def load(self) -> str:
        if not self.path.is_file():
            raise FileNotFoundError("尚未保存 Zoho 应用专用密码")
        if not hasattr(ctypes, "windll"):
            raise OSError("密码安全存储仅支持 Windows")

        encrypted = base64.b64decode(self.path.read_bytes(), validate=True)
        source, source_buffer = _blob(encrypted)
        output = DATA_BLOB()
        success = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise ctypes.WinError()
        try:
            decrypted = ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
        return decrypted.decode("utf-8")
