# Qwen Scouting Readiness

Status: ready; initial panel complete.

- Model: `qwen3.6:latest`, digest prefix `07d35212591f`, 36.0B, Q4_K_M.
- Runtime: Ollama 0.31.2, local OpenAI-compatible API.
- Context: 262,144 tokens.
- Sampling: seed 42, temperature 0, top-p 1, reasoning effort none.
- Maximum workers: 3; Kubernetes B0 compile recovery used 1 worker.
- Observed residency after execution: 29 GB, 100% GPU.
- Smoke: 8/8 runs, validators, native COMPLETE receipts, and cleanup.
- Initial panel: 70/70 runs and native COMPLETE receipts; 62 validator passes.
- Discordant repeat: 8/8 runs and native COMPLETE receipts.

The five large-repository B0 compiles exceeded the original 180-second compile
cap. They were recovered without changing tasks or B0 by using a resume-only,
single-worker 600-second compile allowance. Future schedules must preregister
that large-repository compile class separately.
