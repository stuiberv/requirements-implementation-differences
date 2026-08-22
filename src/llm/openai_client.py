from openai import OpenAI

from models import ValidationResult


class OpenAIClient:
    def __init__(self, model: str = "gpt-5.6-terra"):
        self.client = OpenAI()
        self.model = model

    def validate(
        self,
        instructions: str,
        input_text: str,
    ) -> ValidationResult:

        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=input_text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "validation_result",
                    "schema": ValidationResult.model_json_schema(),
                    "strict": True,
                }
            },
        )

        print("\n=== RAW LLM RESPONSE ===")
        print(response.output_text)

        return ValidationResult.model_validate_json(
            response.output_text
        )