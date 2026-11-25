"""Rule-based advisor: objective, ranked fine-tuning techniques, hyperparameters and
models, each with the reasons behind it.

The rules encode widely reported findings, e.g.
  * LoRA learns less and forgets less than full FT; full FT wins on large, far-from-pretraining
    data (Biderman et al., 2024, "LoRA Learns Less and Forgets Less").
  * QLoRA matches 16-bit LoRA closely at ~1/4 of the base-weight memory (Dettmers et al., 2023).
  * DoRA improves on LoRA at equal rank, especially at low rank (Liu et al., 2024).
  * Prompt tuning becomes competitive only at larger model scales (Lester et al., 2021).
  * DPO / KTO / ORPO / SimPO choice follows the shape of the feedback data.
  * GRPO needs a programmatic reward; it works best from an instruct / SFT checkpoint.
"""

import math

from .catalog import GPUS, MODELS, PERMISSIVE, gpu_spec, model_arch
from .estimator import FULL_LIKE, estimate, memory_breakdown, resolve_strategy
from .testing import required_n, winrate_n

METHOD_INFO = {
    "full": ("Full fine-tuning", "Highest ceiling on large, novel data", "Most memory; forgets more; one full checkpoint per task"),
    "lora": ("LoRA", "Strong default; small adapters; preserves base skills", "Learns less on big domain shifts"),
    "qlora": ("QLoRA", "Fits large models on small GPUs", "~30–40% slower than LoRA; tiny quality gap"),
    "dora": ("DoRA", "Better than LoRA at the same rank", "~10–20% slower; fewer serving stacks support it unmerged"),
    "freeze": ("Partial (top-N layers)", "Simple, cheap; good for classification heads", "Limited capacity for generation tasks"),
    "ia3": ("IA³", "Tiny adapters (~0.01% params); great for many tenants / few examples", "Lower ceiling than LoRA"),
    "prompt_tuning": ("Prompt tuning", "Smallest artifact; no weight changes", "Competitive only on large models"),
    "galore": ("GaLore", "Full-parameter learning with low optimizer memory", "Slower; less mature tooling"),
}

OBJECTIVES = {
    "sft": "SFT", "cpt": "Continued pretraining", "dpo": "DPO", "orpo": "ORPO", "simpo": "SimPO", "kto": "KTO",
    "grpo": "GRPO", "classifier": "Classification head", "distill": "Knowledge distillation", "reward_model": "Reward model",
}

SCHEMA_FOR = {"sft": "messages", "cpt": "text", "dpo": "preference", "orpo": "preference", "simpo": "preference",
              "kto": "kto", "grpo": "prompt_only", "classifier": "text_label", "distill": "messages", "reward_model": "preference"}


def _n(cfg, k, d):
    try:
        v = cfg.get(k)
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def choose_objective(cfg):
    kind = cfg.get("data_kind", "sft")
    task = cfg.get("task_type", "instruction")
    variant = cfg.get("model_variant", "instruct")
    pipeline, alts, why = [], [], []
    if kind == "preference":
        if variant == "base":
            obj = "orpo"
            why.append("Preference data on a base checkpoint: ORPO combines SFT and preference learning in one stage with no reference model.")
            alts = ["dpo", "simpo"]
            pipeline = ["ORPO on (prompt, chosen, rejected)"]
        else:
            obj = "dpo"
            why.append("Paired preferences on an instruct/SFT model: DPO is the most battle-tested offline method.")
            alts = ["simpo", "orpo", "kto"]
            pipeline = ["(optional) SFT on chosen responses", "DPO with β≈0.1", "Check win rate and response length drift"]
    elif kind == "binary_feedback":
        obj = "kto"
        why.append("Unpaired thumbs-up/down signals: KTO learns directly from binary feedback without constructing pairs.")
        alts = ["dpo"]
        pipeline = ["KTO with balanced desirable/undesirable weights"]
    elif kind == "verifiable":
        obj = "grpo"
        why.append("Prompts with checkable answers: GRPO optimises a programmatic reward without a critic model.")
        alts = ["rloo", "sft"]
        pipeline = ["SFT warm-start on a few hundred solved examples" if variant == "base" else "Start from the instruct checkpoint",
                    "GRPO with accuracy + format rewards", "Track reward, completion length and pass@1 on held-out"]
    elif kind == "raw_text":
        obj = "cpt"
        why.append("Unlabelled domain text: continued pretraining teaches vocabulary and knowledge; follow with SFT to restore chat behaviour.")
        alts = ["sft"]
        pipeline = ["Continued pretraining (mix 5–20% general data to limit forgetting)", "SFT on instruction data", "(optional) DPO"]
    elif kind == "labels" or task == "classification":
        obj = "classifier"
        why.append("Fixed label set: a classification head is faster, calibrated and cheaper to serve than generating labels.")
        alts = ["sft"]
        pipeline = ["Sequence classification head + adapters", "Calibrate thresholds on validation"]
    else:
        obj = "sft"
        why.append("Demonstration data: supervised fine-tuning with loss on completions only.")
        alts = ["distill"] if cfg.get("teacher_model") else []
        pipeline = ["SFT", "Evaluate vs base", "(optional) DPO on model samples ranked by a judge"]
    return dict(id=obj, name=OBJECTIVES.get(obj, obj), why=why, alternatives=[dict(id=a, name=OBJECTIVES.get(a, a.upper())) for a in alts], pipeline=pipeline)


def _method_cfg(cfg, method, obj):
    c = dict(cfg, method=method, objective=obj, grad_checkpointing="full", dist_strategy="auto")
    if method == "qlora":
        c["optimizer"] = "paged_adamw_8bit"
    if method in FULL_LIKE:
        c["per_device_batch"] = min(int(_n(cfg, "per_device_batch", 4)), 4)
    return c


def score_methods(cfg, obj):
    a = model_arch(cfg)
    N = _n(cfg, "num_examples", 10000)
    shift = cfg.get("domain_shift", "medium")
    prio = cfg.get("priority", "balanced")
    out = []
    base = dict(lora=70, qlora=62, dora=68, full=60, galore=48, freeze=45, ia3=40, prompt_tuning=32)
    for m, s in base.items():
        reasons = []

        def adj(d, text):
            nonlocal s
            s += d
            reasons.append(dict(delta=d, text=text))

        if N < 1000:
            if m == "full": adj(-20, f"Only {int(N)} examples: full FT overfits easily")
            if m in ("ia3", "prompt_tuning"): adj(+15, "Very few examples favour tiny parameter counts")
            if m == "lora": adj(+5, "Low-rank update regularises small datasets")
        elif N < 10000:
            if m == "full": adj(-10, "Under 10k examples rarely justifies full FT")
        elif N > 100000:
            if m == "full": adj(+15, f"{int(N):,} examples can use full capacity")
            if m == "galore": adj(+8, "Large data benefits from full-parameter updates")
            if m == "dora": adj(+3, "DoRA narrows the gap to full FT on larger data")
        if shift == "high" or obj == "cpt":
            if m in ("full", "galore"): adj(+15, "Large domain shift: full-parameter updates learn new knowledge best")
            if m in ("lora", "qlora", "dora"): adj(-5, "LoRA learns less on far-from-pretraining domains (use high rank)")
            if m in ("ia3", "prompt_tuning"): adj(-15, "Too little capacity for a large domain shift")
        elif shift == "low":
            if m == "full": adj(-5, "Small shift: adapters capture it at a fraction of the cost")
        if cfg.get("preserve_general", True):
            if m in ("lora", "qlora", "dora"): adj(+6, "Adapters forget less of the base model's general skills")
            if m == "full": adj(-8, "Full FT has the highest catastrophic-forgetting risk")
        if prio == "quality":
            if m == "full": adj(+10, "Quality priority: highest ceiling")
            if m == "dora": adj(+6, "Quality priority: DoRA > LoRA at equal rank")
            if m == "qlora": adj(-4, "Quality priority: small 4-bit quantization penalty")
        elif prio == "cost":
            if m == "qlora": adj(+12, "Cost priority: smallest GPUs")
            if m == "lora": adj(+4, "Cost priority: cheap to train and store")
            if m == "full": adj(-15, "Cost priority: most expensive option")
        elif prio == "speed":
            if m == "lora": adj(+8, "Speed priority: fastest PEFT method")
            if m == "qlora": adj(-8, "Speed priority: dequantization slows every step")
            if m == "dora": adj(-4, "Speed priority: DoRA adds per-step overhead")
        if cfg.get("deploy_target") == "multi_tenant":
            if m in ("lora", "qlora"): adj(+10, "Multi-tenant: vLLM / SGLang serve many LoRA adapters on one base")
            if m == "ia3": adj(+5, "Multi-tenant: extremely small adapters")
            if m in ("full", "galore", "freeze"): adj(-25, "Multi-tenant: a full model per tenant is impractical")
        if obj == "classifier":
            if m == "freeze": adj(+15, "Classification: training the top layers + head works well")
            if m == "prompt_tuning": adj(-10, "Prompt tuning is weak for classification heads")
        if obj in ("grpo", "rloo", "ppo"):
            if m == "lora": adj(+5, "Online RL: LoRA weights sync to the rollout engine cheaply")
            if m == "qlora": adj(-6, "Online RL: 4-bit base complicates vLLM rollouts")
        if a["params"] < 10 and m == "prompt_tuning":
            adj(-12, "Prompt tuning lags well behind LoRA below ~10B parameters")

        mc = _method_cfg(cfg, m, obj)
        strategy = resolve_strategy(mc)
        mem = memory_breakdown(mc, strategy)
        if not mem["fits"]:
            adj(-60, f"Does not fit: needs ~{mem['total_gb']:.0f} GB/GPU of {mem['gpu_mem_gb']} GB")
        elif strategy == "zero3_offload":
            adj(-15, "Fits only with CPU offload (much slower)")
        name, pro, con = METHOD_INFO[m]
        out.append(dict(id=m, name=name, score=max(0, min(100, round(s))), fits=mem["fits"], mem_gb=round(mem["total_gb"], 1),
                        strategy=strategy, pro=pro, con=con, reasons=reasons))
    out.sort(key=lambda x: (-x["fits"], -x["score"]))
    return out


def _round_seq(p95, ctx):
    for L in (256, 512, 1024, 2048, 3072, 4096, 6144, 8192, 12288, 16384, 32768, 65536, 131072):
        if L >= p95 * 1.05:
            return min(L, ctx)
    return ctx


def _lr(method, obj, params_b):
    full = method in FULL_LIKE
    table = {
        "dpo": (5e-7, 5e-6), "kto": (5e-7, 5e-6), "simpo": (8e-7, 1e-5), "orpo": (8e-6, 5e-5),
        "grpo": (1e-6, 1e-5), "rloo": (1e-6, 1e-5), "reward_model": (1e-5, 1e-4), "cpt": (2e-5, 1e-4),
    }
    if obj in table:
        return table[obj][0 if full else 1]
    if method in ("full", "galore"):
        return 2e-5 if params_b < 3 else 1e-5 if params_b < 15 else 5e-6 if params_b < 40 else 2e-6
    return {"freeze": 5e-5, "ia3": 3e-3, "prompt_tuning": 3e-2, "prefix": 1e-2, "qlora": 2e-4}.get(
        method, 1e-4 if params_b >= 30 else 2e-4)


def hyperparams(cfg, method, obj):
    a, g = model_arch(cfg), gpu_spec(cfg)
    N = _n(cfg, "num_examples", 10000)
    p95 = _n(cfg, "p95_tokens", 1500)
    avg = _n(cfg, "avg_tokens", 512)
    W = max(1, int(_n(cfg, "num_gpus", 1))) * max(1, int(_n(cfg, "num_nodes", 1)))
    patch, why = {}, []

    def put(k, v, reason):
        patch[k] = v
        why.append(dict(key=k, value=v, why=reason))

    put("objective", obj, "Matches the shape of your data")
    put("record_schema", SCHEMA_FOR.get(obj, "messages"), "Schema the trainer expects for this objective")
    put("method", method, "Top-ranked technique")

    if method in ("lora", "qlora", "dora", "adalora"):
        r = 8 if N < 5000 else 16 if N < 50000 else 32 if N < 300000 else 64
        if cfg.get("domain_shift") == "high" or obj == "cpt":
            r = min(256, r * 4)
        put("lora_r", r, f"Rank scaled to {int(N):,} examples" + (" and a large domain shift" if r >= 64 else ""))
        rs = r >= 64
        put("use_rslora", rs, "rsLoRA keeps updates stable at high rank" if rs else "Not needed below r=64")
        put("lora_alpha", r if rs else 2 * r, "alpha = r with rsLoRA" if rs else "alpha = 2r (scale 2)")
        put("lora_dropout", 0.05 if N < 50000 else 0.0, "Light dropout for small/medium data" if N < 50000 else "Large data: dropout unnecessary")
        put("target_modules", ["all-linear"], "Adapting all linear layers (incl. MLP) beats attention-only")
        if obj == "cpt" and cfg.get("domain_shift") == "high":
            put("modules_to_save", "embed_tokens,lm_head", "New domain vocabulary benefits from training embeddings")
    if method == "qlora":
        put("quant_bits", 4, "4-bit NF4 is the QLoRA sweet spot")
        put("quant_type", "nf4", "NF4 is information-optimal for normally distributed weights")
        put("double_quant", True, "Saves ~3 GB on a 65B model")
        put("compute_dtype", "bfloat16" if g["bf16"] else "float16", "Matches GPU support")
    if method == "freeze":
        put("trainable_layers", max(2, a["layers"] // 8), "Top ~1/8 of layers")

    lr = _lr(method, obj, a["params"])
    put("learning_rate", lr, f"Typical stable LR for {METHOD_INFO.get(method, (method,))[0]} + {OBJECTIVES.get(obj, obj)}")

    if obj in ("dpo", "kto", "simpo", "orpo", "grpo", "rloo"):
        ep = 2 if (obj in ("dpo", "kto") and N < 5000) else 1
    elif obj == "cpt":
        ep = 1
    else:
        ep = 5 if N < 1000 else 3 if N < 5000 else 2 if N < 50000 else 1
    put("epochs", ep, "More passes for small data, one pass for large data / preference / RL")

    sched = "constant_with_warmup" if obj in ("grpo", "rloo") else "warmup_stable_decay" if (obj == "cpt" and N > 100000) else "cosine"
    put("lr_scheduler", sched, {"constant_with_warmup": "Constant LR is standard for online RL",
                                "warmup_stable_decay": "WSD lets you extend pretraining runs and decay at the end"}.get(sched, "Cosine decay is the robust default"))
    put("warmup_ratio", 0.1 if obj in ("dpo", "kto", "simpo", "orpo", "grpo") else 0.03, "Longer warmup stabilises preference/RL losses")
    put("weight_decay", 0.1 if (method in FULL_LIKE and obj == "cpt") else 0.01 if method in FULL_LIKE else 0.0,
        "Weight decay matters for full-parameter updates; adapters rarely need it")

    seq = _round_seq(p95, a["ctx"])
    if obj in ("grpo", "rloo"):
        seq = _round_seq(p95 + _n(cfg, "max_completion_len", 1024), a["ctx"])
    put("max_seq_len", seq, f"Covers p95 length ({int(p95)} tokens) without wasting activation memory")
    if p95 * 1.05 > a["ctx"]:
        put("rope_scaling", "yarn", "p95 length exceeds the model's context window")
        put("rope_factor", round(p95 / a["ctx"] + 0.5, 1), "Scale factor to reach the required length")
    pack = "varlen" if (obj in ("sft", "cpt") and avg / max(p95, 1) < 0.5 and g["fa2"]) else "none"
    put("packing", pack, "Short, variable-length examples: contamination-free packing saves 2–5× compute" if pack == "varlen"
        else "Packing is off (pairwise / RL objectives or uniform lengths)")

    put("precision", "bf16" if g["bf16"] else "fp16", "bf16 avoids loss scaling" if g["bf16"] else f"{cfg.get('gpu_type')} lacks bf16")
    put("attn_impl", "flash_attention_2" if g["fa2"] else "sdpa", "FlashAttention-2 supported" if g["fa2"] else "No FA2 on this GPU; SDPA instead")
    put("use_liger", True, "Fused kernels cut activation + logits memory")
    if obj == "sft" and N < 20000:
        put("neftune_alpha", 5, "NEFTune noise improves small instruction datasets")

    # pick the largest micro-batch that fits, then grad accumulation for the target effective batch
    target = (16 if N < 2000 else 32 if N < 20000 else 64 if N < 200000 else 128)
    if obj in ("dpo", "kto", "simpo", "orpo"):
        target = 32 if N < 10000 else 64
    trial = dict(cfg, **patch)
    trial["optimizer"] = "paged_adamw_8bit" if method == "qlora" else "adamw_torch_fused"
    best_b, ckpt = 1, "full"
    for ck in ("off", "full"):
        trial["grad_checkpointing"] = ck
        fit = next((b for b in (16, 8, 4, 2, 1) if (b * W <= target or b == 1)
                    and memory_breakdown(dict(trial, per_device_batch=b), resolve_strategy(dict(trial, per_device_batch=b)))["fits"]), None)
        # prefer no recompute, but not at the cost of a tiny micro-batch
        if fit and (ck == "full" or fit >= min(4, target // W or 1)):
            best_b, ckpt = fit, ck
            break
    ga = max(1, math.ceil(target / (best_b * W)))
    if obj in ("grpo", "rloo"):
        G = int(_n(cfg, "num_generations", 8))
        while (best_b * W * ga) % G:
            ga += 1
    put("per_device_batch", best_b, "Largest micro-batch that fits")
    put("grad_accum", ga, f"Reaches an effective batch of ~{best_b * W * ga}")
    put("grad_checkpointing", ckpt, "Not needed: memory fits" if ckpt == "off" else "Needed to fit activations")
    trial.update(per_device_batch=best_b, grad_accum=ga, grad_checkpointing=ckpt)

    if method == "qlora":
        put("optimizer", "paged_adamw_8bit", "Paged 8-bit states absorb memory spikes")
    elif method in FULL_LIKE and not memory_breakdown(dict(trial, optimizer="adamw_torch_fused"), resolve_strategy(trial))["fits"]:
        put("optimizer", "adamw_8bit", "8-bit Adam states save 6 bytes/param")
    else:
        put("optimizer", "adamw_torch_fused", "Fused AdamW is fastest when memory allows")
    trial["optimizer"] = patch["optimizer"]
    put("dist_strategy", resolve_strategy(trial), "Least-communication strategy that fits in memory")

    if obj in ("dpo", "kto"):
        put("ref_model", "copy" if method in FULL_LIKE else "peft_disabled",
            "Full FT needs a frozen copy" if method in FULL_LIKE else "Disabling the adapter gives the reference for free")
    if obj in ("dpo", "orpo", "kto"):
        put("pref_beta", 0.1, "Standard β; raise to stay closer to the reference")
    if obj == "simpo":
        put("pref_beta", 2.0, "SimPO uses a larger β (2–2.5) with γ/β ≈ 0.25–0.5")
        put("simpo_gamma", 0.5, "Target reward margin")
    if obj == "grpo":
        put("num_generations", 16 if cfg.get("priority") == "quality" else 8, "Group size for the relative advantage")
        put("kl_coef", 0.0, "No KL term: saves a reference model and works well in practice")
        put("grpo_loss_type", "dr_grpo", "Removes GRPO's length bias")
        put("use_vllm_gen", True, "vLLM makes rollouts 5–10× faster")
    if obj == "classifier":
        put("class_weights", "balanced", "Protects minority classes")

    task = cfg.get("task_type", "instruction")
    metrics = {
        "classification": (["accuracy", "f1_macro", "calibration"], "f1_macro", ["mmlu"]),
        "extraction": (["exact_match", "f1_micro", "json_valid"], "f1_micro", ["ifeval"]),
        "summarization": (["rouge_l", "bertscore"], "judge_winrate", ["ifeval"]),
        "code": (["pass_at_k"], "pass_at_1", ["humaneval", "mbpp"]),
        "reasoning": (["exact_match"], "accuracy", ["gsm8k", "math", "gpqa"]),
        "rag": (["exact_match", "rouge_l"], "judge_winrate", ["ifeval"]),
        "tool_use": (["json_valid", "exact_match"], "accuracy", ["ifeval"]),
        "embedding": (["accuracy"], "ndcg", []),
    }.get(task, (["rouge_l"], "judge_winrate", ["ifeval", "mt_bench", "alpaca_eval"]))
    put("task_metrics", metrics[0], f"Standard metrics for {task}")
    put("primary_metric", metrics[1], "Headline metric for the go/no-go decision")
    put("benchmarks", sorted(set(metrics[2] + (["mmlu"] if cfg.get("preserve_general", True) else []))), "Task benchmarks + a general-skills regression check")
    if task in ("code",):
        put("eval_num_samples", 10, "Samples per prompt for pass@k")

    dep = cfg.get("deploy_target", "cloud_gpu")
    a = model_arch(cfg)

    # ── fine-tuning-specific testing
    prio = cfg.get("priority")
    lora_like = method in ("lora", "qlora", "dora", "adalora")
    online = obj in ("grpo", "rloo", "ppo")
    pre = ["template_render", "truncation", "trainable_audit", "throughput"]
    if obj not in ("dpo", "orpo", "simpo", "kto", "cpo", "reward_model") and not online:
        pre.insert(1, "loss_mask")
    if lora_like and cfg.get("lora_init", "default") in ("default", "gaussian"):
        pre.append("identity_init")
    if not online:
        pre += ["initial_loss", "overfit_batch"]
        if N < 50000 or prio == "quality":
            pre.append("lr_range")
    put("preflight_checks", pre, "Catches template, masking, adapter and gradient bugs in minutes"
        + ("; DPO's step-0 loss must equal ln 2" if obj == "dpo" else "") + ("; loss checks skipped for online RL" if online else ""))
    put("preflight_block", True, "Never launch the full run on a broken pipeline")
    mon = ["nan_guard", "loss_spike", "grad_spike", "lr_check"]
    if not online:
        mon.append("gen_gap")
    if obj in ("dpo", "kto", "simpo", "orpo", "cpo"):
        mon += ["dpo_displacement", "dpo_reward_acc"]
    if online:
        mon += ["rl_reward_hacking", "rl_entropy", "rl_zero_std"] + (["rl_kl"] if _n(cfg, "kl_coef", 0) > 0 else [])
    if obj != "classifier" and resolve_strategy(dict(cfg, **patch)) not in ("fsdp", "zero3", "zero3_offload"):
        mon.append("sample_gens")
    put("monitors_train", mon, {"dpo": "DPO failure modes: likelihood displacement and over-optimisation", "grpo": "RL failure modes: reward hacking, entropy collapse, dead groups"}.get(obj, "Generic divergence / overfitting monitors"))
    ck = "best_task_metric" if (obj in ("dpo", "kto", "simpo", "orpo", "grpo", "rloo", "sft") and obj != "classifier") else "best_val_loss"
    if method in ("full", "galore") and N > 100000:
        ck = "soup"
    put("ckpt_selection", ck, {"best_task_metric": "Loss and task quality diverge for generative / preference objectives",
                               "soup": "Averaging late full-FT checkpoints is a cheap, robust gain",
                               "best_val_loss": "Validation loss tracks quality for this objective"}[ck])
    if ck in ("best_task_metric", "soup"):
        put("save_total_limit", max(int(_n(cfg, "save_total_limit", 3)), 6), "Keep enough checkpoints to select from")
    diag = ["generalization_gap", "stop_behavior", "length_drift"]
    if obj not in ("classifier", "cpt", "reward_model") and task not in ("classification", "embedding"):
        diag.append("safety_erosion")
    if obj in ("dpo", "simpo", "orpo", "kto", "grpo", "rloo") or method == "full":
        diag.append("diversity")
    if task in ("reasoning", "extraction", "classification") or obj in ("dpo", "grpo"):
        diag.append("calibration_drift")
    if lora_like and patch.get("merge_adapters", True):
        diag.append("merge_equivalence")
    if task in ("instruction", "rag", "tool_use"):
        diag.append("template_robustness")
    if obj in ("dpo", "simpo", "kto") or task == "instruction":
        diag.append("sycophancy")
    if task == "domain" or obj == "cpt":
        diag += ["knowledge_probes", "unknown_facts"]
    put("ft_diagnostics", diag, "Side effects fine-tuning is known to cause for this objective, task and method")
    objt = {"sft": ["sft_heldout_ppl"], "distill": ["sft_heldout_ppl", "distill_agreement"], "cpt": ["cpt_ppl"],
            "dpo": ["pref_accuracy", "lc_winrate"], "simpo": ["pref_accuracy", "lc_winrate"], "orpo": ["pref_accuracy", "lc_winrate"],
            "kto": ["lc_winrate"], "cpo": ["pref_accuracy"], "reward_model": ["rm_accuracy"], "grpo": ["rl_passk", "rl_hack_probes"],
            "rloo": ["rl_passk", "rl_hack_probes"], "ppo": ["rl_passk", "rl_hack_probes"], "classifier": ["cls_report"]}.get(obj, [])
    put("objective_tests", objt, f"What success means for {OBJECTIVES.get(obj, obj)}")
    tech = {"lora": ["adapter_norms"] + (["rank_ablation"] if N >= 5000 else []), "dora": ["adapter_norms"],
            "qlora": ["adapter_norms", "qlora_bf16_merge"], "adalora": ["adapter_norms"],
            "full": ["weight_drift"], "galore": ["weight_drift"], "freeze": ["frozen_checksum"], "bitfit": ["frozen_checksum"],
            "prompt_tuning": ["prompt_seed_sensitivity"], "prefix": ["prompt_seed_sensitivity"]}.get(method, [])
    if dep == "multi_tenant" and lora_like:
        tech.append("adapter_isolation")
    put("technique_tests", tech, f"Checks tied to how {METHOD_INFO.get(method, (method,))[0]} changes the weights")
    put("learning_curve", N < 50000, "Small data: a learning curve shows whether more data is the next lever" if N < 50000 else "Large data: skip")
    put("hpo", prio == "quality", "Quality priority: a short successive-halving search over LR and rank" if prio == "quality" else "Defaults are strong; search later if gates fail")
    if prio == "quality":
        put("hpo_method", "asha", "Successive halving spends most compute on promising configs")
        put("hpo_space", ["learning_rate", "lora_r"] if lora_like else (["learning_rate", "beta"] if obj in ("dpo", "kto", "simpo", "orpo") else ["learning_rate", "epochs"]),
            "The settings with the largest effect for this method")
    put("label_noise_audit", task in ("classification", "extraction") or obj == "reward_model", "Human labels: review the highest-loss examples"
        if task in ("classification", "extraction") or obj == "reward_model" else "Not a labelling task")

    # ── testing methodology
    priv, prio = cfg.get("data_privacy"), cfg.get("priority")
    sets = ["in_dist", "golden", "ood"]
    if task in ("safety", "tool_use", "rag", "reasoning", "code"):
        sets.append("adversarial")
    put("test_sets", sets, "Held-out + golden behaviour suite + OOD" + (" + adversarial cases (attack-prone task)" if "adversarial" in sets else ""))
    base_p = _n(cfg, "baseline_value", 0.7)
    base_p = base_p if 0 < base_p < 1 else 0.7
    mde = 0.02 if prio == "quality" else 0.05 if prio in ("cost", "speed") else 0.03
    put("mde", mde, f"Smallest change worth acting on for a '{prio}' priority")
    need = required_n(mde, base_p)
    cur_ratio = _n(cfg, "test_ratio", 0.05)
    if N * cur_ratio < need:
        ratio = min(0.2, math.ceil(need / max(N, 1) * 100) / 100)
        put("test_ratio", ratio, f"≈{need:,} test items detect a {mde:.2f} change at 80% power"
            + ("" if N * ratio >= need else f" — still short: collect more test data ({int(N * ratio):,} of {need:,})"))
    binary = task in ("classification", "reasoning", "extraction", "tool_use")
    put("sig_test", "mcnemar" if binary else "paired_bootstrap",
        "Paired binary outcomes → McNemar" if binary else "Continuous / judge scores → paired bootstrap")
    put("compare_against", ["base", "prompted_baseline"] + (["champion"] if cfg.get("baseline_value") not in (None, "") else []),
        "A fine-tune must beat the base and a well-prompted baseline" + (" and the current production system" if cfg.get("baseline_value") not in (None, "") else ""))
    put("perturbations", ["typos", "case", "whitespace", "template"] + (["distractor"] if task in ("rag", "extraction") else []),
        "Cheap, deterministic robustness probes" + (" + irrelevant-context distractors for retrieval-style inputs" if task in ("rag", "extraction") else ""))
    put("assertion_types", ["contains", "regex", "exact"] + (["json_schema"] if task in ("extraction", "tool_use") or cfg.get("output_format") == "json" else [])
        + (["tool_call"] if task == "tool_use" else []) + (["numeric"] if task == "reasoning" else []) + (["judge_rubric"] if task in ("instruction", "summarization", "safety") else []),
        "Assertion types that match this task's outputs")
    grounding = {"rag": ["faithfulness", "answer_relevancy", "citation_accuracy", "context_precision"], "summarization": ["faithfulness", "selfcheck"],
                 "instruction": ["selfcheck"], "domain": ["selfcheck"]}.get(task, [])
    put("grounding_methods", grounding, "Hallucination checks suited to this task" if grounding else "Outputs are verifiable directly; no grounding layer needed")
    judge = task not in ("classification", "embedding")
    put("judge_enabled", judge, "Open-ended outputs need a judge" if judge else "Exact metrics suffice for this task")
    if judge:
        put("judge_calibration", True, "Validate the judge against human labels before trusting it")
        put("position_swap", True, "Removes position bias in pairwise judging")
    human = judge and (prio == "quality" or task in ("summarization", "safety", "instruction"))
    put("human_eval", human, "Generative quality is ultimately a human judgement" if human else "Automatic metrics are reliable for this task")
    if human:
        need_h = winrate_n(mde)
        put("human_n", max(200, min(1000, need_h)), f"≈{need_h:,} pairwise items detect a {mde:.2f} win-rate edge"
            + (" — capped at 1,000 for annotation cost; the judge (calibrated on these labels) covers the rest" if need_h > 1000 else ""))
        put("annotators_per_item", 3, "Three raters allow majority vote and agreement (Fleiss' κ)")
    suites = []
    if task in ("safety", "instruction", "rag", "tool_use") or dep in ("cloud_gpu", "multi_tenant"):
        suites += ["harmbench", "xstest", "custom_safety"]
    if task in ("rag", "tool_use"):
        suites.append("prompt_injection")
    if priv == "regulated":
        suites.append("pii_leak")
    put("safety_suites", suites, "Jailbreak + over-refusal for user-facing models" + (", injection for tool/RAG inputs" if "prompt_injection" in suites else "")
        + (", PII leakage for regulated data" if priv == "regulated" else "") if suites else "Internal non-generative use")
    put("red_team_tool", "garak" if suites else "none", "Automated probe sweep before release" if suites else "Not needed")
    put("memorization_test", priv == "regulated", "Regulated data must not be extractable" if priv == "regulated" else "Data is not sensitive")
    seeds = 3 if (prio == "quality" and a["params"] <= 10) else 1
    put("train_seeds", seeds, "Small model + quality priority: 3 seeds separate real gains from noise" if seeds > 1 else "One seed; compare effects to the CI width")
    put("quant_degradation_check", True, "Test the artifact you actually ship")
    put("load_test", dep != "mobile", "Verify the latency budget under concurrency" if dep != "mobile" else "Benchmark on-device instead")
    put("gate_max_p95_ms", int(_n(cfg, "latency_p95_ms", 2000)), "Gate on the latency budget from Objective")
    put("rollout", "ab" if dep in ("cloud_gpu", "multi_tenant") else "shadow", "Shadow first, then an A/B test with sequential monitoring"
        if dep in ("cloud_gpu", "multi_tenant") else "Shadow traffic validates before any user sees it")
    if dep in ("cpu_edge", "mobile"):
        put("ptq_method", "gguf", "llama.cpp GGUF runs on CPUs and laptops")
        put("gguf_quant", "Q4_K_M", "Best size/quality trade-off for 4-bit GGUF")
        put("serving_engine", "llamacpp", "CPU / edge serving")
        put("merge_adapters", True, "GGUF needs merged weights")
    elif dep == "multi_tenant":
        put("merge_adapters", False, "Keep adapters separate for per-tenant routing")
        put("multi_lora", True, "One base, many adapters")
        put("serving_engine", "vllm", "Mature multi-LoRA batching")
    else:
        put("merge_adapters", True, "Merged weights have zero adapter latency")
        put("serving_engine", "vllm", "High-throughput default")
        if _n(cfg, "latency_p95_ms", 2000) < 500:
            put("ptq_method", "awq", "Tight latency: 4-bit AWQ roughly doubles decode speed")
            put("spec_decoding", "eagle", "Speculative decoding cuts per-token latency")
    if cfg.get("data_privacy") == "regulated":
        put("pii_scrub", "presidio", "Regulated data: NER-based PII removal")
        put("push_to_hub", False, "Regulated data: keep artifacts in your own registry")
    return patch, why


def suggest_models(cfg, method, obj):
    dep, prio = cfg.get("deploy_target", "cloud_gpu"), cfg.get("priority", "balanced")
    hi = 4 if dep in ("cpu_edge", "mobile") else 9 if (_n(cfg, "latency_p95_ms", 2000) < 500 or prio in ("cost", "speed")) else 80
    lo = 0 if dep in ("cpu_edge", "mobile") else 3 if cfg.get("task_type") in ("reasoning", "code", "instruction") else 0
    out = []
    for mid, spec in MODELS.items():
        if cfg.get("license_constraint") == "permissive" and spec["license"] not in PERMISSIVE:
            continue
        c = _method_cfg(dict(cfg, base_model=mid), method, obj)
        mem = memory_breakdown(c, resolve_strategy(c))
        in_band = lo <= spec["params"] <= hi
        out.append(dict(id=mid, params_b=spec["params"], license=spec["license"], fits=mem["fits"],
                        mem_gb=round(mem["total_gb"], 1), in_band=in_band))
    out.sort(key=lambda x: (not (x["fits"] and x["in_band"]), not x["fits"], -x["params_b"]))
    return dict(size_band=[lo, hi], models=out[:6])


def warnings(cfg, obj, method, ranked):
    a, g = model_arch(cfg), gpu_spec(cfg)
    w = []
    if not any(r["fits"] for r in ranked):
        w.append("No technique fits this model on the selected hardware. Add GPUs, choose a larger-memory GPU or a smaller model.")
    if _n(cfg, "num_examples", 0) < 200:
        w.append("Fewer than 200 examples: consider prompting / few-shot or synthetic augmentation before fine-tuning.")
    if obj in ("dpo", "kto", "simpo") and cfg.get("model_variant") == "base":
        w.append("Preference optimisation on a base model rarely works: run SFT first (or use ORPO).")
    if not g["bf16"]:
        w.append(f"{cfg.get('gpu_type')} has no bf16 or FlashAttention-2: expect fp16 loss-scaling and slower attention.")
    if cfg.get("license_constraint") == "permissive" and a["license"] not in PERMISSIVE:
        w.append(f"{a['id']} uses the '{a['license']}' licence, not a permissive one.")
    if obj == "grpo" and cfg.get("data_kind") != "verifiable":
        w.append("GRPO needs a reward you can compute; without one use a reward model or DPO.")
    if cfg.get("data_privacy") == "regulated" and cfg.get("teacher_model"):
        w.append("Regulated data + external teacher model: confirm the teacher API is approved for this data.")
    if method in FULL_LIKE and cfg.get("deploy_target") == "multi_tenant":
        w.append("Full fine-tuning produces one full model per tenant.")
    return w


def recommend(cfg):
    objective = choose_objective(cfg)
    obj = objective["id"]
    ranked = score_methods(cfg, obj)
    forced = cfg.get("_force_method")
    top = forced if forced in METHOD_INFO else ranked[0]["id"]
    patch, why = hyperparams(cfg, top, obj)
    if forced:
        why[2]["why"] = "Chosen by you (overrides the ranking)"
    est = estimate(dict(cfg, **patch))
    return dict(
        objective=objective, techniques=ranked, patch=patch, rationale=why,
        models=suggest_models(cfg, top, obj), warnings=warnings(cfg, obj, top, ranked), estimate=est,
    )
