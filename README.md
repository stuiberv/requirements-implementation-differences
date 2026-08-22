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

## Status

Early prototype / proof of concept.

The current goal is to establish the basic requirements-to-implementation validation workflow before adding more advanced capabilities such as:

- automatic implementation discovery
- test coverage analysis
- deployment/configuration validation
- CI/CD integration
- implementation and test-generation agents
- multi-agent workflows

## Security

API keys and other credentials must be supplied through environment variables and must not be committed to the repository.