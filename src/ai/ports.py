from abc import ABC, abstractmethod


class TextGenerationPort(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError
