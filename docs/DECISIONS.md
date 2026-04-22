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
- **Status**: Superseded (April 2026)
- **Context**: GLM-OCR is a specialized model with an internal layout analysis
  pipeline triggered by specific keywords.
- **Decision**: Initially used the canonical `"Text Recognition:"` prompt for the
  whole document. Superseded by ADR-013's Two-Pass strategy.
- **Rationale**: Faster inference but failed to preserve column association on
  complex Swiss wholesaler layouts.

---

## [ADR-010] Mandatory Human-in-the-loop Review
- **Status**: Decided (April 2026)
- **Context**: Automated extraction, while accurate, can still make subtle errors in VAT mapping or merchant identification. For financial data, 100% accuracy is required before booking in bexio.
- **Decision**: Transition the system to a mandatory manual review workflow. All receipts processed by the automated pipeline (Folder Watcher, Google Drive) must be held in the Review Dashboard for human approval.
- **Rationale**:
  - **Security**: Prevents erroneous data from being pushed to the accounting system.
  - **Compliance**: Ensures a human has verified the tax implications (VAT rates) of each transaction.
  - **Usability**: The dashboard provides a high-fidelity environment for correcting minor extraction artifacts before they become permanent records.
## [ADR-011] Three-Step LLM Pipeline (Searcher -> Assigner -> Classifier)
- **Status**: Decided (April 2026)
- **Context**: ADR-005 introduced a two-step process for VAT extraction. However, assigning granular booking accounts (e.g., 4200 vs 4201) requires product-level context that is missing from the isolated VAT snippet.
- **Decision**: Add a third step: **Step 3 (Account Classifier)**. This step takes the full OCR text and the resolved receipt to assign accounts per VAT rate.
- **Rationale**:
- **Accuracy**: Separation of concerns ensures math stability (Step 2) while maintaining semantic context (Step 3).
- **Efficiency**: Step 3 only runs if Step 2 succeeds, saving LLM tokens on invalid extractions.

## [ADR-012] Per-VAT-Rate Account Mapping & Learning Loop
- **Status**: Decided (April 2026)
- **Context**: Standard merchant-level account mapping fails for merchants like Prodega or Coop, where a single receipt can contain both Food (2.6%) and Non-Food (8.1%) items requiring different accounts.
- **Decision**: Implement a composite mapping key `(merchant_name, vat_rate)`. Trigger database updates only when a human approves the bill in the dashboard.
- **Rationale**:
- **Precision**: Enables automatic, high-fidelity booking for complex wholesaler receipts.
- **Reliability**: Restricting the "learning" to human-verified approvals prevents LLM hallucinations from polluting the mapping database.
- **Transparency**: The UI displays the AI's reasoning and confidence for its suggested accounts.

## [ADR-013] Two-Pass OCR (Full Text + Table Crop)
- **Status**: Superseded (April 2026)
- **Context**: Complex Swiss layouts (e.g., Prodega, Coop) contain mixed tables
  where column data (Base, VAT, Total) must be mathematically verified. Standard
  `"Text Recognition:"` on the whole image often merges columns, causing
  Step 2 extraction to fail.
- **Decision**: Initially implemented a two-pass strategy with manual cropping. Superseded by ADR-014's native SDK layout handling.

---

## [ADR-014] Migration from Ollama to GLM-OCR SDK (vLLM Backend)
- **Status**: Decided (April 2026)
- **Context**: While Ollama provided a convenient wrapper for GLM-OCR, it lacked support for the specialized PP-DocLayoutV3 layout analysis and the high-fidelity table parsing required for complex Swiss receipts.
- **Decision**: Migrate the OCR engine from the legacy Ollama `glm-ocr` model to the official `glmocr` SDK running in `selfhosted` mode (connecting to a vLLM/SGLang backend).
- **Rationale**:
  - **High Fidelity**: PP-DocLayoutV3 enables accurate multi-point bounding boxes and logical reading order, significantly reducing cascading errors in table parsing.
  - **Native PDF Support**: The SDK handles PDF files natively, removing the need for manual image rendering and external dependencies like `pdf2image`.
  - **Structural Integrity**: The SDK returns a structured `PipelineResult` with native Markdown and JSON layouts, eliminating the need for the heuristic "Two-Pass OCR" crop strategy (ADR-013).
  - **Performance**: vLLM backend provides superior inference throughput and lower latency compared to Ollama for the heavy GLM-OCR vision-encoder.

## [ADR-015] Vision-First Multimodal Architecture (Qwen3.5)
- **Status**: Decided (April 2026)
- **Context**: The legacy pipeline relied on a multi-step "OCR -> Layout -> LLM Extraction" process. While robust, the "OCR-first" approach often lost semantic context between the image and text, requiring complex "Step 2" and "Step 3" LLM calls to reconstruct tabular relationships.
- **Decision**: Migrate to a "Vision-First" strategy using **Qwen3.5-9B** via vLLM's multimodal interface. Implement a Strategy Pattern (`DocumentProcessor`) to maintain the legacy OCR pipeline as a fallback.
- **Rationale**:
  - **Zero-Loss Table Parsing**: Qwen3.5's multimodal encoder processes the raw image pixels alongside the text prompt, enabling it to "see" table borders and column alignments that OCR-first systems often misinterpret.
  - **Reduced Latency**: Consolidates 3+ sequential LLM calls into a single high-fidelity vision-language inference.
  - **Strategy Pattern**: Decoupling the extraction logic from the core pipeline via `DocumentProcessor` ensures long-term flexibility (e.g., swapping for future models or falling back to OCR in low-VRAM environments).
  - **Structured Outputs**: Leverages vLLM's `json_schema` response format for 100% schema compliance at the model level, eliminating the need for post-extraction "VAT math" validation logic in most cases.
