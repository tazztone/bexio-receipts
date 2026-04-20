# Architecture Decision Records (ADR)

This document tracks significant technical decisions and the context behind them.

## ADR Format
When adding a new ADR, use the following format:
```markdown
## [ADR-XXX] Title
- **Status**: Proposed / Decided / Superseded
- **Context**: Describe the problem or situation.
- **Decision**: Clearly state the chosen approach.
- **Rationale**: Explain the reasoning, trade-offs, and benefits.
```

---

## [ADR-001] Use Pydantic AI instead of raw OpenAI SDK
- **Status**: Decided (March 2024)
- **Context**: The initial plan was to use OpenAI's `chat.completions.parse`.
- **Decision**: Switched to `pydantic-ai`.
- **Rationale**: 
  - **Provider Agnostic**: Easily switch between OpenAI, Ollama, and Anthropic.
  - **Type Safety**: Built-in validation of the structured output.
  - **Resilience**: Orchestrates retries and system prompts more cleanly.

## [ADR-002] Multi-Engine OCR (Paddle vs GLM)
- **Status**: Superseded (April 2026)
- **Context**: Supported both PaddleOCR (local sync) and GLM-OCR (Ollama async).
- **Decision**: Initially supported both, but consolidated to GLM-OCR only in ADR-009.

---

## [ADR-009] Consolidate on GLM-OCR Only
- **Status**: Decided (April 2026)
- **Context**: Maintaining PaddleOCR added ~1GB of dependencies and complex threading logic. GLM-OCR proved significantly more accurate for complex Swiss layouts.
- **Decision**: Remove PaddleOCR and make GLM-OCR the sole OCR engine.
- **Rationale**: 
  - **Simplicity**: Dramatically reduces codebase complexity and dependency footprint.
  - **Stability**: Eliminates thread-safety issues with Paddle's C++ extensions.
  - **Quality**: GLM-OCR's multimodal approach handles handwritten and low-contrast receipts better.

## [ADR-003] Use bexio v4 Expenses Payload
- **Status**: Corrected
- **Context**: Early documentation research used legacy or incorrect field names (`gross_total`, etc.).
- **Decision**: Strictly follow the modern `expenses` payload (using UUIDs and `paid_on`).
- **Rationale**: Prevents silent API rejection and future-proofs the integration.

## [ADR-005] Two-Step OCR Extraction (Transcribe -> Parse)
- **Status**: Decided (April 2024)
- **Context**: Vision models (VLMs) like GLM-OCR frequently hallucinate or skip columns in complex financial tables when forced to output structured JSON directly.
- **Decision**: Decouple transcription from extraction. The VLM now outputs GitHub-Flavored Markdown (GFM), which is then parsed by a text-only LLM.
- **Rationale**: GFM preserves spatial column relationships (Base | VAT | Total) which are critical for math validation.

## [ADR-006] Image Resolution Capping
- **Status**: Decided (April 2024)
- **Context**: Large phone photos (12MP+) create bloated base64 payloads and high latency without adding significant OCR value.
- **Decision**: Cap all incoming images to a maximum long-edge of 2560px.
- **Rationale**: Optimal balance for GLM-OCR's 336px patch grid. Reduces bandwidth by ~60% and lowers inference latency while maintaining sub-millimeter text legibility.

## [ADR-007] Image Format (WebP)
- **Status**: Decided (May 2024)
- **Context**: JPEG encoding creates "ringing" artifacts around text edges, which can confuse character recognition.
- **Decision**: Standardize on **WebP (q90)** for all OCR payloads.
- **Rationale**: Better text sharpness at smaller file sizes than JPEG q80.

## [ADR-008] GLM-OCR Prompt Strategy
- **Status**: Decided (May 2024)
- **Context**: GLM-OCR is a specialized model with an internal layout analysis pipeline triggered by specific keywords.
- **Decision**: Use the canonical `"Text Recognition:"` prompt. Avoid free-form instructions or complex formatting requests.
- **Rationale**: Faster inference and more stable internal table detection (PP-DocLayout-V3).

---

## [ADR-010] Mandatory Human-in-the-loop Review
- **Status**: Decided (April 2026)
- **Context**: Automated extraction, while accurate, can still make subtle errors in VAT mapping or merchant identification. For financial data, 100% accuracy is required before booking in bexio.
- **Decision**: Transition the system to a mandatory manual review workflow. All receipts processed by the automated pipeline (Folder Watcher, Google Drive) must be held in the Review Dashboard for human approval.
- **Rationale**:
  - **Security**: Prevents erroneous data from being pushed to the accounting system.
  - **Compliance**: Ensures a human has verified the tax implications (VAT rates) of each transaction.
  - **Usability**: The dashboard provides a high-fidelity environment for correcting minor extraction artifacts before they become permanent records.
