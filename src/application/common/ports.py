from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager


class UnitOfWorkPort(ABC):
    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]:
        raise NotImplementedError


class IdGeneratorPort(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError
