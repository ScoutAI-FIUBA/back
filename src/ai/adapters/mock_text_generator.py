from src.ai.ports import TextGenerationPort


class MockTextGenerator(TextGenerationPort):
    def generate(self, prompt: str) -> str:
        return f"mock-response:{prompt}"
