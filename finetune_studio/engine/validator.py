"""Preflight checks: catch incompatible or risky settings before a GPU-hour is spent."""

from .catalog import gpu_spec, model_arch
from .estimator import FULL_LIKE, estimate
from .testing import summary as test_summary

PREF = {"dpo", "orpo", "simpo", "kto", "cpo", "reward_model"}
ONLINE = {"grpo", "rloo", "ppo"}
EXPECTED_SCHEMA = {
    "sft": {"messages", "alpaca", "prompt_completion"}, "distill": {"messages", "alpaca", "prompt_completion", "prompt_only"},
    "cpt": {"text"}, "dpo": {"preference"}, "orpo": {"preference"}, "simpo": {"preference"}, "cpo": {"preference"},
    "reward_model": {"preference"}, "kto": {"kto", "preference"}, "grpo": {"prompt_only"}, "rloo": {"prompt_only"},
    "ppo": {"prompt_only"}, "classifier": {"text_label"},
}


def _n(cfg, k, d=0.0):
    try:
        v = cfg.get(k)
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def validate(cfg):
    issues = []
    a, g = model_arch(cfg), gpu_spec(cfg)
    m, obj = cfg.get("method", "lora"), cfg.get("objective", "sft")

    def add(level, stage, key, msg):
        issues.append(dict(level=level, stage=stage, key=key, msg=msg))

    est = estimate(cfg)
    mem = est["memory"]
    if not mem["fits"]:
        add("error", "compute", "gpu_type",
            f"Estimated {mem['total_gb']:.1f} GB/GPU exceeds {g['mem']} GB. Try QLoRA, gradient checkpointing, a smaller micro-batch, "
            "ZeRO-3/FSDP or more GPUs.")
    elif mem["total_gb"] > g["mem"] * 0.85:
        add("warn", "compute", "per_device_batch", f"Memory is tight ({mem['total_gb']:.1f} of {g['mem']} GB); fragmentation may cause OOM.")

    exp = EXPECTED_SCHEMA.get(obj)
    if exp and cfg.get("record_schema") not in exp:
        add("error", "data", "record_schema", f"{obj.upper()} expects a {' / '.join(sorted(exp))} schema, not '{cfg.get('record_schema')}'.")
    if obj in PREF | ONLINE and cfg.get("packing", "none") != "none":
        add("error", "data", "packing", "Packing is not supported for preference or online-RL objectives.")
    if cfg.get("packing") == "naive":
        add("warn", "data", "packing", "Naive packing lets examples attend to each other; prefer contamination-free packing.")
    if cfg.get("packing") == "varlen" and cfg.get("attn_impl") not in ("flash_attention_2", "flash_attention_3"):
        add("error", "data", "packing", "Contamination-free packing needs FlashAttention (varlen kernels).")
    if obj == "cpt" and cfg.get("train_on_completions"):
        add("info", "data", "train_on_completions", "Continued pretraining trains on all tokens; completion-only masking is ignored.")
    if _n(cfg, "max_seq_len", 2048) > a["ctx"] and cfg.get("rope_scaling", "none") == "none":
        add("error", "model", "rope_scaling", f"max_seq_len exceeds the model context ({a['ctx']}). Enable RoPE scaling or shorten.")
    if _n(cfg, "p95_tokens", 0) > _n(cfg, "max_seq_len", 2048) * 1.1:
        add("warn", "data", "max_seq_len", "More than 5% of examples will be truncated at the current max_seq_len.")
    if _n(cfg, "val_ratio") + _n(cfg, "test_ratio") > 0.4:
        add("warn", "data", "val_ratio", "Validation + test take over 40% of the data.")
    if _n(cfg, "test_ratio") == 0:
        add("warn", "data", "test_ratio", "No held-out test split: final metrics will be optimistic.")

    if not g["bf16"] and cfg.get("precision") == "bf16":
        add("error", "training", "precision", f"{cfg.get('gpu_type')} does not support bf16; use fp16.")
    if cfg.get("precision") == "fp8" and not str(cfg.get("gpu_type", "")).startswith(("H100", "H200", "B200", "MI300")):
        add("error", "training", "precision", "FP8 training needs Hopper/Blackwell (or MI300).")
    if not g["fa2"] and str(cfg.get("attn_impl", "")).startswith("flash"):
        add("error", "model", "attn_impl", f"FlashAttention is not supported on {cfg.get('gpu_type')}; use SDPA.")
    if cfg.get("attn_impl") == "flash_attention_3" and not str(cfg.get("gpu_type", "")).startswith(("H100", "H200")):
        add("error", "model", "attn_impl", "FlashAttention-3 targets Hopper GPUs.")
    if cfg.get("precision") == "fp16" and m in FULL_LIKE:
        add("warn", "training", "precision", "fp16 full fine-tuning is prone to overflow; prefer bf16.")

    lr = _n(cfg, "learning_rate", 2e-4)
    if m in FULL_LIKE and lr > 1e-4:
        add("error", "training", "learning_rate", f"LR {lr:g} is very high for full fine-tuning (typical 5e-6 – 2e-5).")
    if m in ("lora", "qlora", "dora") and lr < 1e-5 and obj in ("sft", "cpt"):
        add("warn", "training", "learning_rate", f"LR {lr:g} is low for LoRA SFT (typical 1e-4 – 3e-4).")
    if obj in ("dpo", "kto", "simpo") and lr > (1e-5 if m not in FULL_LIKE else 2e-6):
        add("warn", "training", "learning_rate", "Preference optimisation is sensitive: LR looks high (DPO full ~5e-7, LoRA ~5e-6).")
    if _n(cfg, "warmup_ratio", 0.03) == 0 and obj in PREF | ONLINE:
        add("warn", "training", "warmup_ratio", "Use warmup (≈0.1) for preference / RL objectives.")
    if est["eff_batch"] < 8 and obj not in ONLINE:
        add("warn", "training", "grad_accum", f"Effective batch {est['eff_batch']} is small; gradients will be noisy.")
    if cfg.get("load_best") and cfg.get("eval_strategy") == "no":
        add("error", "training", "load_best", "load_best_model_at_end requires an eval strategy.")
    if cfg.get("eval_strategy") == "steps" and _n(cfg, "save_steps", 200) % max(1, _n(cfg, "eval_steps", 200)) and cfg.get("load_best"):
        add("error", "training", "save_steps", "With load_best, save_steps must be a multiple of eval_steps.")
    if _n(cfg, "early_stopping_patience") > 0 and cfg.get("eval_strategy") == "no":
        add("error", "training", "early_stopping_patience", "Early stopping needs evaluation enabled.")
    if est["steps"] < 50:
        add("info", "training", "epochs", f"Only {est['steps']} optimizer steps; consider a smaller effective batch.")
    if cfg.get("optimizer", "").startswith("paged") and m not in ("qlora", "lora", "dora"):
        add("info", "training", "optimizer", "Paged optimizers mainly help QLoRA memory spikes.")

    if m in ("lora", "qlora", "dora", "adalora"):
        r, alpha = _n(cfg, "lora_r", 16), _n(cfg, "lora_alpha", 32)
        if r >= 64 and not cfg.get("use_rslora"):
            add("info", "technique", "use_rslora", "Rank ≥ 64: rsLoRA usually trains more stably.")
        if alpha / max(r, 1) > 4 and not cfg.get("use_rslora"):
            add("warn", "technique", "lora_alpha", f"alpha/r = {alpha / r:g} is large; updates may be unstable.")
        if not cfg.get("target_modules"):
            add("error", "technique", "target_modules", "Select at least one target module.")
        if cfg.get("lora_init") == "loftq" and m != "qlora":
            add("warn", "technique", "lora_init", "LoftQ initialisation is designed for quantized bases.")
    if m == "qlora" and cfg.get("dist_strategy") in ("fsdp", "zero3") and cfg.get("quant_storage") != "bfloat16":
        add("error", "technique", "quant_storage", "Sharding QLoRA with FSDP/ZeRO-3 needs quant_storage = bfloat16.")
    if m == "dora" and cfg.get("merge_adapters") is False and cfg.get("multi_lora"):
        add("warn", "deploy", "multi_lora", "Unmerged DoRA adapters are not supported by every multi-LoRA server.")
    if cfg.get("add_special_tokens") and m not in FULL_LIKE and "embed" not in str(cfg.get("modules_to_save", "")):
        add("error", "technique", "modules_to_save", "New special tokens need embed_tokens,lm_head in modules_to_save.")
    if cfg.get("use_unsloth") and int(_n(cfg, "num_gpus", 1)) * int(_n(cfg, "num_nodes", 1)) > 1:
        add("warn", "model", "use_unsloth", "Unsloth's open-source build targets single-GPU training.")

    if obj in ("dpo", "kto") and m in FULL_LIKE and cfg.get("ref_model") == "peft_disabled":
        add("error", "alignment", "ref_model", "Full fine-tuning has no adapter to disable; use a frozen copy or precomputed log-probs.")
    if obj in PREF and cfg.get("model_variant") == "base" and obj != "orpo":
        add("warn", "alignment", "objective", "Preference optimisation on a base model: run SFT first or use ORPO.")
    if obj in ONLINE:
        W = int(_n(cfg, "num_gpus", 1)) * int(_n(cfg, "num_nodes", 1))
        G = int(_n(cfg, "num_generations", 8))
        if (int(_n(cfg, "per_device_batch", 4)) * W * int(_n(cfg, "grad_accum", 1))) % G:
            add("error", "alignment", "num_generations", "Effective batch (micro-batch × GPUs × accumulation) must be divisible by the group size.")
        if not cfg.get("reward_sources"):
            add("error", "alignment", "reward_sources", "Online RL needs at least one reward.")
        if m == "qlora" and cfg.get("use_vllm_gen"):
            add("warn", "alignment", "use_vllm_gen", "vLLM rollouts with a 4-bit bitsandbytes base are slow or unsupported; prefer LoRA.")
    if obj == "distill" and not cfg.get("teacher_model_id"):
        add("error", "alignment", "teacher_model_id", "Distillation needs a teacher model.")
    if obj == "classifier" and _n(cfg, "num_labels", 2) < 2:
        add("error", "alignment", "num_labels", "Need at least two labels.")

    if cfg.get("data_privacy") == "regulated":
        if cfg.get("push_to_hub") and not cfg.get("hub_private"):
            add("error", "tracking", "hub_private", "Regulated data: never push to a public hub repo.")
        if cfg.get("pii_scrub") == "none":
            add("warn", "data", "pii_scrub", "Regulated data with no PII scrubbing.")
    if cfg.get("push_to_hub") and not cfg.get("hub_model_id"):
        add("error", "tracking", "hub_model_id", "Set a hub repo id to push.")
    if cfg.get("spot") and not cfg.get("checkpoint_uri"):
        add("warn", "compute", "checkpoint_uri", "Spot instances without remote checkpoints can lose work on preemption.")
    if not cfg.get("decontaminate") and cfg.get("benchmarks"):
        add("warn", "data", "decontaminate", "Benchmarks without decontamination can overstate results.")
    if cfg.get("ptq_method") == "gguf" and not cfg.get("merge_adapters"):
        add("error", "export", "merge_adapters", "GGUF export needs merged weights.")
    if cfg.get("multi_lora") and cfg.get("merge_adapters"):
        add("warn", "deploy", "multi_lora", "Multi-LoRA serving needs unmerged adapters.")
    if cfg.get("multi_lora") and m in FULL_LIKE:
        add("error", "deploy", "multi_lora", "Multi-LoRA serving requires an adapter method.")
    if _n(cfg, "serve_max_len", 8192) > a["ctx"] and cfg.get("rope_scaling", "none") == "none":
        add("warn", "deploy", "serve_max_len", "Serving length exceeds the model's native context.")

    # ── fine-tuning-specific testing
    pre = set(cfg.get("preflight_checks") or [])
    lora_like = m in ("lora", "qlora", "dora", "adalora")
    if not pre:
        add("warn", "ft_testing", "preflight_checks", "No pre-training sanity checks: template and loss-mask bugs typically surface only after the run.")
    if "identity_init" in pre and not (lora_like or m in ("vera", "ia3")):
        add("info", "ft_testing", "preflight_checks", "Zero-init identity only applies to adapter methods; it will be skipped.")
    if "identity_init" in pre and cfg.get("lora_init") in ("pissa", "olora", "loftq"):
        add("info", "ft_testing", "preflight_checks", f"{cfg.get('lora_init')} re-factorises base weights, so the identity check is skipped.")
    if obj in ONLINE and pre & {"overfit_batch", "initial_loss", "lr_range", "loss_mask"}:
        add("info", "ft_testing", "preflight_checks", "Loss-based sanity checks are skipped for online RL (losses need rollouts).")
    mons = set(cfg.get("monitors_train") or [])
    if obj in ("dpo", "kto", "simpo", "orpo", "cpo") and not mons & {"dpo_displacement", "dpo_reward_acc"}:
        add("warn", "ft_testing", "monitors_train", "Preference training without DPO monitors: likelihood displacement goes unnoticed until evaluation.")
    if obj in ONLINE and not mons & {"rl_reward_hacking", "rl_entropy"}:
        add("warn", "ft_testing", "monitors_train", "Online RL without reward-hacking / entropy monitors.")
    if mons & {"dpo_displacement", "dpo_reward_acc"} and obj not in ("dpo", "kto", "simpo", "orpo", "cpo"):
        add("info", "ft_testing", "monitors_train", "DPO monitors are inactive for this objective.")
    if mons & {"rl_reward_hacking", "rl_entropy", "rl_kl", "rl_zero_std"} and obj not in ONLINE:
        add("info", "ft_testing", "monitors_train", "RL monitors are inactive for this objective.")
    if "sample_gens" in mons and cfg.get("dist_strategy") in ("fsdp", "zero3", "zero3_offload"):
        add("info", "ft_testing", "monitors_train", "Sample generations are skipped with sharded parameters (FSDP / ZeRO-3).")
    if "gen_gap" in mons and cfg.get("eval_strategy") == "no":
        add("warn", "ft_testing", "monitors_train", "The overfitting monitor needs evaluation during training.")
    ck = cfg.get("ckpt_selection", "final")
    evals = max(1, int(estimate(cfg)["steps"] / max(_n(cfg, "save_steps", 200), 1)))
    if ck in ("best_task_metric", "soup") and int(_n(cfg, "save_total_limit", 3)) < min(evals, 5):
        add("warn", "ft_testing", "ckpt_selection", f"Only {int(_n(cfg, 'save_total_limit', 3))} checkpoints are kept: raise save_total_limit to select among more.")
    if ck == "soup" and int(_n(cfg, "soup_k", 3)) > int(_n(cfg, "save_total_limit", 3)):
        add("error", "ft_testing", "soup_k", "soup_k exceeds the number of checkpoints kept (save_total_limit).")
    if ck == "best_val_loss" and obj in ("dpo", "grpo", "rloo", "simpo", "kto"):
        add("warn", "ft_testing", "ckpt_selection", "Validation loss is a poor proxy for preference / RL objectives; select on a task metric.")
    if (cfg.get("hpo") or cfg.get("learning_curve") or cfg.get("data_ablation")) and cfg.get("eval_strategy") == "no":
        add("error", "ft_testing", "hpo", "Search / learning curves score trials on eval_loss: enable evaluation.")
    if cfg.get("data_ablation") and not str(cfg.get("data_mixing") or "").strip():
        add("warn", "ft_testing", "data_ablation", "Source ablation needs a dataset mixture (Data → Dataset mixture).")
    if cfg.get("learning_curve") and _n(cfg, "num_examples", 0) < 1000:
        add("info", "ft_testing", "learning_curve", "Under 1k examples the small fractions are too noisy to fit a curve.")
    if cfg.get("hpo") and "lora_r" in (cfg.get("hpo_space") or []) and not lora_like:
        add("info", "ft_testing", "hpo_space", "LoRA rank is not searchable for this method.")
    diag = set(cfg.get("ft_diagnostics") or [])
    if "merge_equivalence" in diag and (not lora_like or not cfg.get("merge_adapters")):
        add("info", "ft_testing", "ft_diagnostics", "Merge equivalence only applies to merged adapters.")
    if m == "qlora" and cfg.get("merge_adapters") and "qlora_bf16_merge" not in (cfg.get("technique_tests") or []):
        add("warn", "ft_testing", "technique_tests", "QLoRA adapters are trained on a 4-bit base but merged onto bf16: test the merge (qlora_bf16_merge).")
    if obj not in ("classifier", "cpt", "reward_model") and "safety_erosion" not in diag and cfg.get("deploy_target") != "cpu_edge":
        add("info", "ft_testing", "ft_diagnostics", "Fine-tuning, even on benign data, can erode safety behaviour; add the safety-erosion check.")
    if (cfg.get("task_type") == "domain" or obj == "cpt") and not diag & {"knowledge_probes", "unknown_facts"}:
        add("info", "ft_testing", "ft_diagnostics", "Knowledge-injection runs: probe recall with paraphrased and reversed questions.")
    objt = set(cfg.get("objective_tests") or [])
    fit = {"sft_heldout_ppl": {"sft", "distill"}, "pref_accuracy": {"dpo", "simpo", "orpo", "cpo"}, "lc_winrate": {"dpo", "simpo", "orpo", "kto", "cpo"},
           "rm_accuracy": {"reward_model"}, "rl_passk": ONLINE, "rl_hack_probes": ONLINE, "distill_agreement": {"distill"},
           "cpt_ppl": {"cpt"}, "cls_report": {"classifier"}}
    off = sorted(t for t in objt if obj not in fit.get(t, {obj}))
    if off:
        add("warn", "ft_testing", "objective_tests", f"{', '.join(off)} do not apply to {obj}.")
    if not objt & {t for t, objs in fit.items() if obj in objs}:
        add("info", "ft_testing", "objective_tests", f"No objective-specific test for {obj}.")
    if "lc_winrate" in objt and not cfg.get("judge_enabled"):
        add("warn", "ft_testing", "lc_winrate", "Length-controlled win rate needs the LLM judge (Evaluation step).")
    tfit = {"rank_ablation": {"lora", "dora", "qlora"}, "adapter_norms": {"lora", "dora", "qlora", "adalora"}, "qlora_bf16_merge": {"qlora"},
            "frozen_checksum": {"freeze", "bitfit", "lora", "qlora", "dora", "adalora", "vera", "ia3", "prefix", "prompt_tuning"},
            "weight_drift": {"full", "galore", "freeze"}, "prompt_seed_sensitivity": {"prompt_tuning", "prefix"}, "adapter_isolation": {"lora", "dora", "qlora"}}
    toff = sorted(t for t in (cfg.get("technique_tests") or []) if m not in tfit.get(t, {m}))
    if toff:
        add("warn", "ft_testing", "technique_tests", f"{', '.join(toff)} do not apply to {m}.")

    # ── testing methodology
    ts = test_summary(cfg)
    sets = set(cfg.get("test_sets") or [])
    ca = set(cfg.get("compare_against") or [])
    task = cfg.get("task_type")
    if "in_dist" in sets and ts["n_test"] and not ts["adequate"]:
        add("warn", "evaluation", "mde", f"Test set ({ts['n_test']:,} items) can only detect changes ≥ {ts['detectable']:.3f}; "
            f"detecting {ts['mde']:.3f} needs ≈{ts['required_n']:,}. Enlarge test_ratio, add test data or raise the MDE.")
    if not sets:
        add("error", "evaluation", "test_sets", "No test sets selected.")
    if not (sets & {"ood", "temporal", "production_sample"}):
        add("info", "evaluation", "test_sets", "Only in-distribution testing: add an OOD, temporal or production sample to measure generalisation.")
    if "golden" not in sets:
        add("info", "evaluation", "test_sets", "No golden behavioural suite: specific regressions can hide inside a stable average.")
    if "prompted_baseline" not in ca:
        add("info", "evaluation", "compare_against", "Compare against a prompt-engineered baseline: the fine-tune must beat the cheap alternative.")
    if cfg.get("gate_require_significance") and cfg.get("sig_test") == "none":
        add("error", "evaluation", "sig_test", "The significance gate needs a significance test.")
    if cfg.get("sig_test") == "mcnemar" and not ({"exact_match", "accuracy", "json_valid"} & set(cfg.get("task_metrics") or [])):
        add("warn", "evaluation", "sig_test", "McNemar needs binary per-item outcomes; use a paired bootstrap for continuous metrics.")
    if cfg.get("judge_enabled") and not cfg.get("judge_calibration"):
        add("info", "evaluation", "judge_calibration", "An uncalibrated judge: validate it against ~100–200 human labels before trusting win rates.")
    if cfg.get("judge_enabled") and not cfg.get("judge_model"):
        add("warn", "evaluation", "judge_model", "Choose a judge model (ideally a different family from the model under test to limit self-preference).")
    if cfg.get("judge_enabled") and cfg.get("judge_mode") != "single" and not cfg.get("position_swap"):
        add("warn", "evaluation", "position_swap", "Pairwise judges have position bias; enable position swapping.")
    if cfg.get("human_eval"):
        if int(_n(cfg, "annotators_per_item", 1)) < 2:
            add("warn", "evaluation", "annotators_per_item", "With one annotator per item, agreement cannot be measured.")
        if int(_n(cfg, "human_n", 0)) < ts["winrate_n"]:
            add("info", "evaluation", "human_n", f"{int(_n(cfg, 'human_n', 0))} items gives limited power; ≈{ts['winrate_n']} detect a {ts['mde']:.2f} win-rate edge.")
    if task == "rag" and not cfg.get("grounding_methods"):
        add("warn", "evaluation", "grounding_methods", "RAG task without grounding/faithfulness tests.")
    if task in ("tool_use", "extraction") and not ({"json_schema", "tool_call"} & set(cfg.get("assertion_types") or [])):
        add("warn", "evaluation", "assertion_types", "Structured-output task: add JSON-schema / tool-call assertions.")
    if cfg.get("ptq_method", "none") != "none" and not cfg.get("quant_degradation_check"):
        add("warn", "evaluation", "quant_degradation_check", "You ship a quantized model but only test the bf16 one.")
    if cfg.get("data_privacy") == "regulated" and not ("pii_leak" in (cfg.get("safety_suites") or []) or cfg.get("memorization_test")):
        add("warn", "evaluation", "memorization_test", "Regulated data: test for PII leakage and training-data memorisation.")
    if task in ("safety", "tool_use", "rag") and not cfg.get("safety_suites") and cfg.get("red_team_tool", "none") == "none":
        add("warn", "evaluation", "safety_suites", f"{task} models are attack surfaces: add jailbreak / prompt-injection tests.")
    if cfg.get("gate_primary") and cfg.get("target_value") in (None, ""):
        add("info", "objective", "target_value", "The primary-metric gate is skipped until you set a target value.")
    if cfg.get("gate_min_winrate") is not None and _n(cfg, "gate_min_winrate", 0.5) > 0 and not cfg.get("judge_enabled"):
        add("info", "evaluation", "judge_enabled", "The win-rate gate needs the LLM judge.")
    if int(_n(cfg, "train_seeds", 1)) == 1 and _n(cfg, "mde", 0.03) < 0.02:
        add("info", "evaluation", "train_seeds", "Effects under 2 points are often within seed-to-seed variance; train ≥3 seeds.")
    if cfg.get("split_strategy") == "random" and "temporal" in sets:
        add("info", "data", "split_strategy", "A random split leaks future data into training; use a temporal split with the temporal test set.")

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order[i["level"]])
    return issues
