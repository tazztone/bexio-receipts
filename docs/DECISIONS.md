# Architecture Decision Records (ADR)

This document tracks significant technical decisions and the context behind them.

## [ADR-001] Use Pydantic AI instead of raw OpenAI SDK
- **Status**: Decided (March 2024)
- **Context**: The initial plan was to use OpenAI's `chat.completions.parse`.
- **Decision**: Switched to `pydantic-ai`.
- **Rationale**: 
  - **Provider Agnostic**: Easily switch between OpenAI, Ollama, and Anthropic.
  - **Type Safety**: Built-in validation of the structured output.
  - **Resilience**: Orchestrates retries and system prompts more cleanly.

## [ADR-002] Multi-Engine OCR (Paddle vs GLM)
- **Status**: Decided
- **Context**: PaddleOCR is fast but sometimes struggles with complex Swiss receipt layouts.
- **Decision**: Support both PaddleOCR (local sync) and GLM-OCR (Ollama async).
- **Rationale**: Allows users to trade-off performance vs. accuracy based on their hardware.

## [ADR-003] Use bexio v4 Expenses Payload
- **Status**: Corrected
- **Context**: Early documentation research used legacy or incorrect field names (`gross_total`, etc.).
- **Decision**: Strictly follow the modern `expenses` payload (using UUIDs and `paid_on`).
- **Rationale**: Prevents silent API rejection and future-proofs the integration.

## [ADR-004] SQLite for Persistence
- **Status**: Decided
- **Context**: Need to track processed files and merchant mappings.
- **Decision**: Use a single SQLite file with WAL mode enabled.
- **Rationale**: Low complexity, high reliability for a single-user system.
