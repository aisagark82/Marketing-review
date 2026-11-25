# Fine-Tune Studio

Plan, check and generate fine-tuning runs for LLMs, covering the whole lifecycle from objective to production monitoring.
It's a local web app (HTML + vanilla JS front end, Python back end) with **no dependencies beyond the Python
standard library**.

```bash
cd finetune_studio
python3 server.py          # opens http://127.0.0.1:8765
python3 -m unittest discover tests
```

## What it does

| Stage | Options covered |
|---|---|
| **1 Objective** | task type, modality, output format, priority (quality/cost/speed), domain shift, forgetting tolerance, deployment target, latency, privacy, licence, success metric |
| **2 Data** | source, data kind, record schema, chat template, completion-only loss, dedup (exact / MinHash / semantic), length + quality + toxicity + language filters, PII scrubbing, decontamination, augmentation (Self-Instruct, Evol-Instruct, distillation, rejection sampling…), split strategies (random / stratified / temporal / grouped), mixtures, curriculum, packing (incl. contamination-free varlen), truncation |
| **3 Base model** | 18 presets or any HF id, revision, attention kernel (FA2/FA3/SDPA), RoPE scaling (linear/dynamic/YaRN/LongRoPE), Liger, Unsloth, pad / special tokens |
| **4 Technique** | Full, partial-freeze, LoRA, QLoRA, DoRA, AdaLoRA, VeRA, IA³, prefix, prompt tuning, BitFit, GaLore, plus rank, alpha, rsLoRA, LoRA+, PiSSA/OLoRA/LoftQ/EVA init, target modules, NF4/FP4, double quant, quant storage |
| **5 Objective fn** | SFT, CPT, DPO (+ IPO/hinge/robust/BCO/SPPO/NCA/APO), ORPO, SimPO, KTO, CPO, GRPO (Dr. GRPO / DAPO), RLOO, PPO, reward model, distillation (forward/reverse KL, GKD), classification head, NEFTune |
| **6 Hyperparameters** | 9 LR schedules incl. WSD, 11 optimizers (AdamW fused/8-bit/paged/4-bit, Adafactor, Lion, schedule-free, Muon…), batching, precision incl. FP8, gradient checkpointing, eval/save cadence, early stopping, determinism |
| **7 Compute** | 12 GPU types, nodes, DDP / FSDP1/2 / ZeRO-1/2/3 / offload, sequence parallelism, launcher, SLURM / K8s / Ray / SageMaker / Vertex…, spot |
| **8 Tracking** | W&B / MLflow / TensorBoard / Comet, run-name templates, hub push, data versioning, environment capture |
| **9 Evaluation & testing** | see [Testing methodology](#testing-methodology) below |
| **10 Optimize & export** | merge, AWQ / GPTQ / GGUF / FP8 / HQQ / bnb, ONNX / TensorRT-LLM / MLX / OpenVINO, pruning, model card |
| **11 Deploy & monitor** | vLLM / SGLang / TGI / TRT-LLM / llama.cpp / Ollama, multi-LoRA, FP8 KV cache, speculative decoding (n-gram / draft / EAGLE-3), guardrails, shadow/canary/A-B rollout, drift/feedback monitors, retraining triggers |

* **Advisor:** recommends the objective from the shape of your data, ranks 8 techniques with a 0–100 score and the
  reasons behind every point, filters by memory fit, sets 30+ hyperparameters with a reason for each, and suggests
  base models that fit your hardware and constraints. You choose which recommendations to apply.
* **Live inspector:** per-GPU memory breakdown (weights / grads / optimizer / activations / logits / extra models),
  trainable parameters, effective batch, steps, wall-clock time, cost and adapter size, all updating as you edit.
* **Preflight checks:** about 50 compatibility and risk rules, such as a DPO schema mismatch, packing with preference
  losses, bf16 on a T4, the GRPO group-size divisibility rule, QLoRA + FSDP storage dtype, an unmerged GGUF, or
  regulated data going to a public hub. Click a check to jump to the setting.
* **Dataset profiler:** drop a JSONL / JSON / CSV file to detect its schema and data kind, see length percentiles and a
  histogram, and flag duplicates, PII and label imbalance. Then apply the detected settings.
* **Pipeline generator:** writes `train.py` (Transformers + PEFT + TRL), `config.yaml`, accelerate / DeepSpeed configs,
  `launch.sh` (incl. SLURM), `eval.sh`, `eval_task.py`, `export.sh`, `serve.sh` and `requirements.txt`. You can
  download them as a zip.
* **UX:** Essential/Expert modes (expert settings stay hidden unless changed), a ⌘K search across every setting, presets,
  modified-from-default markers with one-click reset, light/dark themes, autosave, and JSON import/export.

## Testing methodology

The Evaluation & testing step treats a fine-tuned model like software under test. The rule is to always
compare against cheaper alternatives, on several distributions, with paired statistics, and to gate the release
in CI.

| Layer | What it checks | How |
|---|---|---|
| Test sets | In-distribution, OOD, temporal, adversarial, sampled production, golden suite | Each scored separately; slice metrics by any field |
| Baselines | Base model, **prompt-engineered baseline**, production model, previous run | Same items, same decoding (paired design) |
| Task metrics | EM, accuracy, token F1, ROUGE-L, JSON validity, pass@k, BLEU / chrF / BERTScore, ECE | Per-item scores feed the significance tests |
| Behavioural (CheckList) | Minimum-functionality, invariance and directional tests | Assertions: exact, contains, not-contains, regex, JSON schema, numeric ± tol, tool-call match, judge rubric |
| Robustness | Typos, casing, whitespace, prompt templates, distractor context, homoglyphs, LLM paraphrase / translation | Metric drop + answer consistency, deterministic seeds |
| LLM-as-judge | Pairwise or rubric scoring | Position swap, optional jury, **calibrated against human labels (Cohen's κ + raw agreement)** |
| Human evaluation | Side-by-side, Likert, ranking, error taxonomy | Blinded randomised pack → labels → win rate + Fleiss' / Cohen's κ |
| Hallucination & grounding | Faithfulness, answer relevancy, context precision, citation accuracy, SelfCheckGPT, FActScore | Built-in heuristics, RAGAS export or judge |
| Safety & privacy | HarmBench, XSTest over-refusal, toxicity, BBQ, prompt injection (canary), PII leakage, memorisation | Custom sets in the suite + garak / PyRIT / promptfoo |
| Regression | General-skills drop vs base (catastrophic forgetting), quantized vs bf16, overfitting, seed variance | lm-eval deltas, paired tests, trainer_state analysis |
| Statistics | Paired bootstrap, McNemar, Wilcoxon, permutation; Holm / BH correction; bootstrap CIs | **Power analysis** sizes the test set and human-eval sample for your minimum detectable effect |
| Load | TTFT, p50/p95 latency, throughput, error rate | vllm bench / GenAI-Perf / Locust / k6 |
| Release gates | Primary target, significance, regression, win rate, behavioural, robustness, safety, over-refusal, quantization, latency, human agreement | `eval_suite.py` exits 1 on failure so CI blocks the release |
| Online | Shadow → canary → A/B | Online success metric, guardrail metrics, sequential testing, minimum duration |

The Advisor recommends a test plan per task. For example, a RAG task gets faithfulness and citation checks plus
prompt-injection tests; classification gets McNemar; regulated data gets PII-leak and memorisation probes. It also
sizes the held-out split so the minimum effect you care about is detectable. The side panel shows the detectable
change and which test layers are enabled.

Generated files: `eval_suite.py` (all layers, two-pass so each model loads once, cached outputs, `--only` / `--limit`),
`TEST_PLAN.md`, `gates.json`, `tests/golden.example.jsonl`, `tests/safety.example.jsonl`, `loadtest.sh`,
`redteam.sh`. Judge and paraphrase calls use any OpenAI-compatible endpoint (`JUDGE_BASE_URL`, `JUDGE_API_KEY`).

## Layout

```
server.py            stdlib HTTP server + JSON API
engine/schema.py     every stage / field / option (UI is rendered from this; add a field here and it appears)
engine/catalog.py    model architectures and GPU specs
engine/estimator.py  memory / time / cost model
engine/recommender.py advisor rules
engine/validator.py  preflight checks
engine/testing.py    power analysis, test-layer coverage, eval_suite.py / TEST_PLAN.md generators
engine/codegen.py    pipeline generator
engine/dataset.py    dataset profiler
static/              index.html, styles.css, app.js
```

API: `GET /api/schema`, `POST /api/analyze | /api/recommend | /api/generate | /api/profile | /api/export.zip`
(body `{"config": {...}}`).

## Accuracy notes

Memory figures are first-order estimates, typically within ~20% of measured peak for Llama-style decoders. Time and
cost assume a fixed MFU per method, so treat them as planning numbers. Token counts in the profiler use ≈4
chars/token. Generated code targets recent TRL / PEFT releases. Trainers that newer TRL moved to `trl.experimental`
are imported with a fallback. Review the generated scripts before running them on real hardware.
