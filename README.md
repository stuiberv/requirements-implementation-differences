# Requirements Implementation Differences

An experimental AI-assisted quality engineering tool that compares software requirements with an implementation and identifies gaps, ambiguities, and engineering risks.

## Current Capabilities

The initial version:

- Clones a GitHub repository.
- Reads a requirements document from the repository.
- Reads specified implementation files.
- Provides repository structure as additional context.
- Uses an LLM to compare requirements against the implementation.
- Produces structured validation results.
- Identifies:
  - satisfied and unsatisfied requirements
  - ambiguous or unverifiable requirements
  - supporting implementation evidence
  - severity and confidence
  - clarification questions
  - engineering risks

## Architecture

The LLM integration is abstracted from the validation agent so that different LLM providers can be supported.

Current structure:

    instructions/
        requirements-validator.md

    src/
        agent.py
        models.py

        llm/
            base.py
            agent_factory.py
            openai_client.py

## Current LLM Support

- OpenAI

Additional LLM providers can be added by implementing the common LLM client interface and registering them with the factory.

## Running the Agent

### Prerequisites

- Python 3.10+
- Git
- An OpenAI API key

### Setup

Clone this repository and open a terminal in the repository directory.

Create a Python virtual environment:

```powershell
uv venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\activate
```

Install the required dependencies:

```powershell
uv pip install openai pydantic
```

Set your OpenAI API key as an environment variable:

```powershell
$env:OPENAI_API_KEY="your-api-key"
```

Do not store or commit your API key in the repository.

### Run

The agent accepts:

- A GitHub repository URL
- A requirements file within that repository
- One or more implementation files within that repository

Run the agent using:

```powershell
python src/agent.py `
  --repo <github-repository-url> `
  --requirements <requirements-file> `
  --implementation <implementation-file> [<additional-implementation-files>]
```

Example:

```powershell
python src/agent.py `
  --repo https://github.com/example/example-site.git `
  --requirements requirements/homepage.md `
  --implementation requirements/index.html requirements/styles.css
```

The agent will:

1. Clone the specified GitHub repository.
2. Read the repository structure.
3. Load the specified requirements.
4. Load the specified implementation files.
5. Send the requirements and implementation evidence to the configured LLM.
6. Return a structured validation result.

The validation result includes requirement-level findings such as:

- Requirement status
- Implementation evidence
- Explanation
- Severity
- Confidence
- Clarification questions when applicable

The agent can also identify engineering risks that are not necessarily direct requirement violations, such as missing test coverage.

## Status

This is an early prototype.

Implementation files must currently be specified explicitly when running the agent. Future versions may automatically identify relevant implementation files based on the requirements and repository structure.

The initial version supports OpenAI as the LLM provider. The LLM integration is abstracted so additional providers can be added later.

The current goal is to establish the basic requirements-to-implementation validation workflow before adding more advanced capabilities such as:

- automatic implementation discovery
- test coverage analysis
- deployment/configuration validation
- CI/CD integration
- implementation and test-generation agents
- multi-agent workflows



## Security

API keys and other credentials must be supplied through environment variables and must not be committed to the repository.