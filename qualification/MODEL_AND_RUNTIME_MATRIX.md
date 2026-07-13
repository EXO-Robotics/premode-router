# Model and Runtime Matrix

Discovery date: 2026-07-13.

| Family | Exact local identity | Quantization | Context | Runtime/API | Status |
| --- | --- | --- | --- | --- | --- |
| Qwen | `qwen3.6:latest`, digest `07d35212591fc27746f0a317c975a6d68754fb38e9053d82e25f06057af28522`, 36.0B | Q4_K_M | 262144 | Ollama 0.31.2; native and OpenAI-compatible local APIs | Installed; not invoked |
| Gemma | None | Not available | Not available | No usable local model/runtime pair | Blocked |
| OSS | None | Not available | Not available | No usable local model/runtime pair | Blocked |

The Qwen runtime reported no resident model at discovery. Tokenizer identity was reported as GPT-2 with the Qwen 3.5 pre-tokenizer; the runtime did not expose a standalone tokenizer hash. The chat template was `{{ .Prompt }}`; no task call was made. Sampling defaults were temperature 1, top-k 20, top-p 0.95, min-p 0, presence penalty 1.5, and repeat penalty 1. Seed behavior was not calibrated.

Host discovery reported approximately 96 GiB unified memory with no active swap pressure. Concurrency and co-residency were not calibrated because the required model families were absent.
