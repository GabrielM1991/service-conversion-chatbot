from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key: str | None) -> None:
        self._fernet = Fernet(key.encode("ascii")) if key else None

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("TENANT_SECRET_KEY no está configurada")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("TENANT_SECRET_KEY no está configurada")
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as error:
            raise RuntimeError("No fue posible descifrar la credencial") from error
