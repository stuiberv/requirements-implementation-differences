from pathlib import Path

from models import ValidationResult
from llm.llm_agent import LLMClient


def validate_repository(
    llm_client: LLMClient,
    repository_structure: str,
    context_text: str,
    requirements_text: str,
    implementation_text: str,
) -> ValidationResult:

    instructions = Path(
        "instructions/requirements-validator.md"
    ).read_text(encoding="utf-8")

    input_text = f"""
REPOSITORY STRUCTURE

{repository_structure}

PROJECT CONTEXT

{context_text}

REQUIREMENTS

{requirements_text}

IMPLEMENTATION

{implementation_text}
"""

    return llm_client.validate(
        instructions=instructions,
        input_text=input_text,
    )