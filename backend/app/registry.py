"""Generic named-factory registry (Open/Closed): add a provider by registering it, not by editing callers."""
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, name: str):
        def deco(factory: Callable[..., T]):
            self._factories[name] = factory
            return factory

        return deco

    def create(self, name: str, **kwargs) -> T:
        if name not in self._factories:
            raise ValueError(f"Unknown {self.kind} '{name}'. Registered: {sorted(self._factories)}")
        return self._factories[name](**kwargs)
