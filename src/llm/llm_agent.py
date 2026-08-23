from typing import Protocol

from models import ValidationResult


class LLMClient(Protocol):
    def validate(
        self,
        instructions: str,
        input_text: str,
    ) -> ValidationResult:
        ...