"""First-order estimates of GPU memory, trainable parameters, time and cost.

These are planning numbers (typically within ~20% of measured peak memory for
Llama-style decoders), not guarantees. The model is:

  memory/GPU = frozen weights + trainable weights + grads + optimizer states (sharded per strategy)
             + activations (per layer, with/without recompute) + logits + extra models
             (reference / teacher / vLLM rollout engine) + CUDA overhead
  time       = training FLOPs / (GPUs × peak TFLOPS × MFU)  (+ rollout time for online RL)
"""

import math

from .catalog import gpu_spec, model_arch

GB = 1024 ** 3

PEFT_METHODS = {"lora", "qlora", "dora", "adalora", "vera", "ia3", "prefix", "prompt_tuning", "bitfit"}
FULL_LIKE = {"full", "galore", "freeze"}

# optimizer state bytes per trainable parameter (excluding master weights)
OPT_STATE_BYTES = {
    "adamw_torch_fused": 8, "adamw_torch": 8, "schedule_free_adamw": 8,
    "adamw_8bit": 2, "paged_adamw_8bit": 2, "paged_adamw_32bit": 8,
    "adamw_torch_4bit": 1, "adafactor": 1, "lion_32bit": 4, "muon": 4, "sgd": 4,
}

LORA_SHAPES = {  # (in, out) as functions of arch
    "q_proj": lambda a: (a["hidden"], a["hidden"]),
    "k_proj": lambda a: (a["hidden"], a["kv"]),
    "v_proj": lambda a: (a["hidden"], a["kv"]),
    "o_proj": lambda a: (a["hidden"], a["hidden"]),
    "gate_proj": lambda a: (a["hidden"], a["inter"]),
    "up_proj": lambda a: (a["hidden"], a["inter"]),
    "down_proj": lambda a: (a["inter"], a["hidden"]),
}


def _f(cfg, key, default):
    v = cfg.get(key, default)
    try:
        return float(v) if v not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _i(cfg, key, default):
    return int(_f(cfg, key, default))


def world_size(cfg):
    return max(1, _i(cfg, "num_gpus", 1)) * max(1, _i(cfg, "num_nodes", 1))


def embed_params(a):
    # untied input + output embeddings for most models above ~3B
    tied = a["params"] < 3.0 or "gemma" in a["id"].lower()
    return a["vocab"] * a["hidden"] * (1 if tied else 2)


def trainable_params(cfg, a):
    n = a["params"] * 1e9
    m = cfg.get("method", "lora")
    L, h = a["layers"], a["hidden"]
    if m in ("full", "galore"):
        return n
    if m == "freeze":
        per_layer = (n - embed_params(a)) / L
        t = per_layer * min(L, _i(cfg, "trainable_layers", 4))
        if cfg.get("train_embeddings"):
            t += a["vocab"] * h
        if cfg.get("train_lm_head", True):
            t += a["vocab"] * h
        return t
    if m in ("lora", "qlora", "dora", "adalora"):
        r = _i(cfg, "lora_r", 16)
        if m == "adalora":
            r = _i(cfg, "adalora_init_r", 12)
        targets = cfg.get("target_modules") or ["all-linear"]
        names = list(LORA_SHAPES) if "all-linear" in targets else [t for t in targets if t in LORA_SHAPES]
        per_layer = sum(r * sum(LORA_SHAPES[t](a)) for t in names)
        if m == "dora":
            per_layer += sum(LORA_SHAPES[t](a)[1] for t in names)
        layers = cfg.get("layers_to_transform") or ""
        n_layers = len([x for x in str(layers).split(",") if x.strip()]) or L
        t = per_layer * min(L, n_layers)
        for extra in ("embed_tokens", "lm_head"):
            if extra in targets:
                t += r * (a["vocab"] + h)
        mts = str(cfg.get("modules_to_save") or "")
        if "embed_tokens" in mts:
            t += a["vocab"] * h
        if "lm_head" in mts:
            t += a["vocab"] * h
        return t
    if m == "vera":
        return L * 7 * (_i(cfg, "vera_r", 256) + h)
    if m == "ia3":
        return L * (2 * a["kv"] + a["inter"])
    if m == "prompt_tuning":
        return _i(cfg, "num_virtual_tokens", 20) * h
    if m == "prefix":
        return _i(cfg, "num_virtual_tokens", 20) * 2 * h * L
    if m == "bitfit":
        return L * (4 * h + 2 * a["kv"] + 2 * a["inter"])
    return n


def _seq_len(cfg):
    max_len = _i(cfg, "max_seq_len", 2048)
    if cfg.get("objective") in ("grpo", "rloo", "ppo"):
        return min(max_len, _i(cfg, "p95_tokens", 512)) + _i(cfg, "max_completion_len", 1024)
    if cfg.get("packing", "none") != "none":
        return max_len
    return min(max_len, _i(cfg, "p95_tokens", max_len))


def _act_bytes_per_token_layer(a, act_b):
    # stored tensors for one Llama-style block (attention + SwiGLU MLP), flash attention
    h, kv, i = a["hidden"], a["kv"], a["inter"]
    return (5 * h + 2 * kv + 4 * i) * act_b


def _strategy_shards(strategy, cfg, W):
    """Divisors for (weights, grads, optimizer) and whether optimizer is offloaded."""
    gpus = max(1, _i(cfg, "num_gpus", 1))
    off = bool(cfg.get("offload_optimizer"))
    if strategy in ("single", "ddp"):
        return 1, 1, 1, off
    if strategy == "zero1":
        return 1, 1, W, off
    if strategy == "zero2":
        return 1, W, W, off
    if strategy == "zero3":
        return W, W, W, off
    if strategy == "zero3_offload":
        return W, W, W, True
    if strategy == "fsdp":
        sh = cfg.get("fsdp_sharding", "FULL_SHARD")
        if sh == "NO_SHARD":
            return 1, 1, 1, off
        if sh == "SHARD_GRAD_OP":
            return 1, W, W, off
        if sh == "HYBRID_SHARD":
            return gpus, gpus, gpus, off
        return W, W, W, off
    return 1, 1, 1, off


def memory_breakdown(cfg, strategy=None):
    a, g = model_arch(cfg), gpu_spec(cfg)
    W = world_size(cfg)
    strategy = strategy or cfg.get("dist_strategy", "auto")
    if strategy == "auto":
        strategy = "single" if W == 1 else "ddp"
    m = cfg.get("method", "lora")
    obj = cfg.get("objective", "sft")
    n = a["params"] * 1e9
    T = trainable_params(cfg, a)
    prec = cfg.get("precision", "bf16")
    w_b = 4 if prec == "fp32" else 2
    act_b = 4 if prec == "fp32" else 2

    # frozen / base weights
    if m == "qlora":
        bits = _i(cfg, "quant_bits", 4)
        qb = (0.5 + (0.016 if cfg.get("double_quant", True) else 0.06)) if bits == 4 else 1.06
        emb = embed_params(a)
        base = (n - emb) * qb + emb * 2
    else:
        base = n * w_b

    opt_state = OPT_STATE_BYTES.get(cfg.get("optimizer", "adamw_torch_fused"), 8)
    if m == "galore":
        opt_state *= min(1.0, _i(cfg, "galore_rank", 128) / a["hidden"])
    if m in FULL_LIKE:
        # base already holds bf16 copy of trainable weights; add bf16 grads + fp32 master + states
        trainable_w = 0
        grads = T * w_b
        optim = T * ((4 if prec != "fp32" else 0) + opt_state)
    else:
        trainable_w = T * 4
        grads = T * 4
        optim = T * opt_state

    dw, dg, do, offload = _strategy_shards(strategy, cfg, W)
    weights_gpu = base / dw + trainable_w / dw
    grads_gpu = grads / dg
    optim_gpu = 0 if offload else optim / do

    # activations
    s = _seq_len(cfg)
    b = _i(cfg, "per_device_batch", 4)
    mult = 2 if obj in ("dpo", "orpo", "simpo", "cpo", "reward_model") else 1
    tokens = s * b * mult
    per_layer = _act_bytes_per_token_layer(a, act_b) * tokens
    ckpt = cfg.get("grad_checkpointing", "full")
    if ckpt == "off":
        acts = per_layer * a["layers"]
    elif ckpt == "offload":
        acts = per_layer * 1.2
    else:
        acts = a["layers"] * tokens * a["hidden"] * act_b + per_layer
    if cfg.get("use_liger", True):
        acts *= 0.85
    if cfg.get("seq_parallel", "none") != "none":
        acts /= W
    logits = tokens * a["vocab"] * 8
    if cfg.get("use_liger", True):
        logits /= 16
    if obj == "classifier":
        logits = tokens * a["hidden"] * 4

    # extra models
    extra = 0.0
    extra_note = ""
    if obj in ("dpo", "kto") and cfg.get("ref_model", "peft_disabled") == "copy":
        extra += n * 2 / dw
        extra_note = "reference model"
    elif obj in ("dpo", "kto") and m in FULL_LIKE and cfg.get("ref_model") != "precompute":
        extra += n * 2 / dw
        extra_note = "reference model (full FT cannot disable an adapter)"
    if obj in ("grpo", "rloo", "ppo"):
        if _f(cfg, "kl_coef", 0.0) > 0 and m in FULL_LIKE:
            extra += n * 2 / dw
        if cfg.get("use_vllm_gen", True) and cfg.get("vllm_mode", "colocate") == "colocate":
            G = _i(cfg, "num_generations", 8)
            kv_tok = 2 * a["layers"] * a["kv"] * 2
            extra += n * 2 + kv_tok * s * G * max(1, b)
            extra_note = "vLLM rollout engine (colocated)"
        if obj == "ppo":
            extra += n * 2 + grads + optim / do  # critic (+ reward model)
            extra_note = "critic + reward model"
    if obj == "distill":
        extra += n * 2  # teacher assumed same size or smaller
        extra_note = "teacher model"

    overhead = 1.5 * GB
    parts = dict(weights=weights_gpu, grads=grads_gpu, optimizer=optim_gpu,
                 activations=acts, logits=logits, extra=extra)
    total = sum(parts.values()) * 1.08 + overhead
    parts["overhead"] = total - sum(parts.values())
    return dict(
        strategy=strategy, parts={k: v / GB for k, v in parts.items()}, total_gb=total / GB,
        gpu_mem_gb=g["mem"], fits=total / GB <= g["mem"] * 0.95, trainable=T, total_params=n,
        extra_note=extra_note, seq_len=s, cpu_offload_gb=(optim / do) / GB if offload else 0.0,
    )


def resolve_strategy(cfg):
    W = world_size(cfg)
    chosen = cfg.get("dist_strategy", "auto")
    if chosen != "auto":
        return chosen
    if W == 1:
        return "single"
    full = cfg.get("method", "lora") in FULL_LIKE
    order = ["ddp", "zero2", "fsdp", "zero3_offload"] if not full else ["zero2", "fsdp", "zero3_offload"]
    for st in order:
        if memory_breakdown(cfg, st)["fits"]:
            return st
    return order[-1]


def estimate(cfg):
    a, g = model_arch(cfg), gpu_spec(cfg)
    W = world_size(cfg)
    strategy = resolve_strategy(cfg)
    mem = memory_breakdown(cfg, strategy)
    m, obj = cfg.get("method", "lora"), cfg.get("objective", "sft")
    n = a["params"] * 1e9

    n_ex = _i(cfg, "num_examples", 10000)
    train_frac = max(0.0, 1 - _f(cfg, "val_ratio", 0.05) - _f(cfg, "test_ratio", 0.05))
    train_ex = n_ex * train_frac
    epochs = _f(cfg, "epochs", 1)
    b, ga = _i(cfg, "per_device_batch", 4), _i(cfg, "grad_accum", 1)
    eff_batch = b * ga * W
    avg, p95, max_len = _i(cfg, "avg_tokens", 512), _i(cfg, "p95_tokens", 1500), _i(cfg, "max_seq_len", 2048)

    if obj in ("grpo", "rloo", "ppo"):
        G = _i(cfg, "num_generations", 8)
        comp = _i(cfg, "max_completion_len", 1024) * 0.6
        tok_per_ex = (min(avg, max_len) + comp) * G
        gen_tokens = train_ex * epochs * G * comp
    else:
        tok_per_ex = min(avg, max_len) if cfg.get("packing", "none") != "none" else min(max_len, (avg + p95) / 2)
        if obj in ("dpo", "orpo", "simpo", "cpo", "reward_model"):
            tok_per_ex *= 2
        gen_tokens = 0
    train_tokens = train_ex * epochs * tok_per_ex

    if cfg.get("packing", "none") != "none" and obj in ("sft", "cpt"):
        steps = math.ceil(train_ex * epochs * avg / max_len / eff_batch)
    else:
        steps = math.ceil(train_ex * epochs / eff_batch)
    if _i(cfg, "max_steps", -1) > 0:
        steps = _i(cfg, "max_steps", -1)
        train_tokens = steps * eff_batch * tok_per_ex

    Tn = mem["trainable"]
    fwd = 2 * n
    bwd = 4 * n if m in ("full", "galore") else 2 * n + 2 * Tn
    flops_tok = fwd + bwd
    if cfg.get("grad_checkpointing", "full") != "off":
        flops_tok += fwd
    if obj in ("dpo", "kto") and cfg.get("ref_model") != "precompute":
        flops_tok += fwd
    if obj == "distill":
        flops_tok += fwd
    flops_tok += 12 * a["layers"] * a["hidden"] * mem["seq_len"] / 2  # attention
    mfu = {"full": 0.38, "galore": 0.30, "freeze": 0.36, "qlora": 0.22}.get(m, 0.32)
    if not g["bf16"]:
        mfu *= 0.7
    if _i(cfg, "num_nodes", 1) > 1:
        mfu *= 0.85
    if strategy == "zero3_offload" or cfg.get("offload_optimizer"):
        mfu *= 0.6
    if cfg.get("use_unsloth"):
        mfu *= 1.5
    peak = g["tflops"] * 1e12
    train_s = train_tokens * flops_tok / (W * peak * mfu)
    gen_s = gen_tokens * 2 * n / (W * peak * 0.08) if gen_tokens else 0
    hours = (train_s + gen_s) / 3600

    return dict(
        model=a["id"], params_b=a["params"], gpu=cfg.get("gpu_type"), world_size=W,
        strategy=strategy, memory=mem,
        trainable_params=Tn, trainable_pct=100 * Tn / n if n else 0,
        adapter_mb=(Tn * 2 / 1024 ** 2) if m in PEFT_METHODS else None,
        eff_batch=eff_batch, tokens_per_step=eff_batch * tok_per_ex, steps=steps,
        train_tokens=train_tokens, gen_tokens=gen_tokens, hours=hours,
        gpu_hours=hours * W, cost=hours * W * g["cost"], cost_per_gpu_hour=g["cost"], mfu=mfu,
    )
