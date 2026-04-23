# Vision Model Performance and Optimization

Vision-Language Models (VLMs) are the core engine of bexio-receipts. This guide
explains why we use them, how they perform on consumer hardware, and how to
optimize them for production.

## BLUF (Bottom Line Up Front)
Processing receipts visually (as images) is significantly more accurate than
processing raw text because the layout provides critical context for financial
rules. On a single RTX 3090 (24 GB), the system can sustain **85+ TPS** using
optimized Qwen 3.6 models.

## Why Visual Rendering?
Even for digital PDFs that already contain a text layer, the `Vision` strategy
renders pages as images at a specific DPI (default 300).

### Visual Layout Cues
Text-based LLMs receive a flat stream of characters, losing the spatial
context. VLMs use the visual arrangement to distinguish between data types:
- **Table Structure**: Physical borders and alignment help accurately map VAT
  rates to their respective totals.
- **Font Weight**: Bolded or larger text often signals the "Grand Total,"
  reducing confusion with sub-totals or tax summaries.
- **Spatial Reasoning**: The model understands that a value in the bottom-right
  is likely a total, even if it appears early or late in a raw text stream.

### Robustness
VLMs are more robust against:
- **Encoding Errors**: Resolving garbled text in digital PDFs by "looking" at
  the shapes.
- **Hybrid Documents**: Capturing handwritten notes, stamps, or signatures
  alongside typed text.

## Hardware Benchmarks (RTX 3090)
The following benchmarks were recorded on a single RTX 3090 (24 GB VRAM) using
the **Qwen3.6-27B-int4-AutoRound** model.

| Metric | Performance |
|---|---|
| **Sustained Throughput** | 85 TPS |
| **Peak Throughput** | 106 TPS |
| **Context Window** | 125K Tokens |
| **VRAM Usage** | 21.3 GB / 24 GB |
| **Power Target** | 230W (Efficient) |

## Optimization Techniques

### 1. Multi-Token Prediction (MTP)
Speculative decoding using MTP heads allows the model to "propose" multiple
tokens at once. For Qwen 3.6, **n=3** is the sweet spot for maximum ROI on
throughput without collapsing draft acceptance.

### 2. TurboQuant KV Cache
To handle long context (100K+ tokens) within 24 GB of VRAM, the system uses
**TurboQuant 4-bit/3-bit** KV cache quantization. This significantly reduces
the memory footprint of the KV pool compared to standard FP16 or FP8 formats.

<!-- prettier-ignore -->
> [!TIP]
> For the highest accuracy and throughput on consumer GPUs, we recommend the
> **Qwen3.6-27B-Uncensored** GGUF model or the **Lorbus AutoRound** variant.

## Next Steps
- Learn how to configure these models in the [Configuration Guide](CONFIGURATION.md).
- Explore the [Architecture](ARCHITECTURE.md) to see how the vLLM backend
  integrates with the pipeline.
