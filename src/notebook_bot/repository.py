"""Интерфейс репозитория: единый контракт для чтения, записи, удаления сущностей и работы с транзакциями независимо от конкретного хранилища."""
###Он позволяет потом заменить временное JSON-хранилище на нормальную БД без переписывания всей логики

from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeVar

from .models import Entity

T = TypeVar("T", bound=Entity)


class Transaction(Protocol):
    async def get(self, model: type[T], id: str) -> T | None: ...
    async def list(self, model: type[T], **filters) -> list[T]: ...
    async def put(self, value: Entity) -> None: ...
    async def delete(self, model: type[T], id: str) -> None: ...


class Repository(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Transaction]: ...
