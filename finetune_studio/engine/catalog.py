"""Reference data: base-model architectures and GPU specs.

Numbers are approximate public figures, used only for memory / time / cost estimates.
Anything not listed can be entered with base_model = "custom".
"""

# params in billions; hidden, layers, intermediate (MLP), kv_dim (n_kv_heads * head_dim), vocab
MODELS = {
    "meta-llama/Llama-3.2-1B": dict(params=1.24, hidden=2048, layers=16, inter=8192, kv=512, vocab=128256, ctx=131072, license="llama3.2"),
    "meta-llama/Llama-3.2-3B": dict(params=3.21, hidden=3072, layers=28, inter=8192, kv=1024, vocab=128256, ctx=131072, license="llama3.2"),
    "meta-llama/Llama-3.1-8B": dict(params=8.03, hidden=4096, layers=32, inter=14336, kv=1024, vocab=128256, ctx=131072, license="llama3.1"),
    "meta-llama/Llama-3.3-70B-Instruct": dict(params=70.6, hidden=8192, layers=80, inter=28672, kv=1024, vocab=128256, ctx=131072, license="llama3.3"),
    "Qwen/Qwen2.5-0.5B": dict(params=0.49, hidden=896, layers=24, inter=4864, kv=128, vocab=151936, ctx=32768, license="apache-2.0"),
    "Qwen/Qwen2.5-7B": dict(params=7.62, hidden=3584, layers=28, inter=18944, kv=512, vocab=152064, ctx=131072, license="apache-2.0"),
    "Qwen/Qwen2.5-14B": dict(params=14.7, hidden=5120, layers=48, inter=13824, kv=1024, vocab=152064, ctx=131072, license="apache-2.0"),
    "Qwen/Qwen2.5-32B": dict(params=32.8, hidden=5120, layers=64, inter=27648, kv=1024, vocab=152064, ctx=131072, license="apache-2.0"),
    "Qwen/Qwen2.5-72B": dict(params=72.7, hidden=8192, layers=80, inter=29568, kv=1024, vocab=152064, ctx=131072, license="qwen"),
    "Qwen/Qwen3-8B": dict(params=8.19, hidden=4096, layers=36, inter=12288, kv=1024, vocab=151936, ctx=131072, license="apache-2.0"),
    "Qwen/Qwen3-32B": dict(params=32.8, hidden=5120, layers=64, inter=25600, kv=1024, vocab=151936, ctx=131072, license="apache-2.0"),
    "mistralai/Mistral-7B-v0.3": dict(params=7.25, hidden=4096, layers=32, inter=14336, kv=1024, vocab=32768, ctx=32768, license="apache-2.0"),
    "mistralai/Mistral-Nemo-Base-2407": dict(params=12.2, hidden=5120, layers=40, inter=14336, kv=1024, vocab=131072, ctx=131072, license="apache-2.0"),
    "google/gemma-2-2b": dict(params=2.61, hidden=2304, layers=26, inter=9216, kv=1024, vocab=256000, ctx=8192, license="gemma"),
    "google/gemma-2-9b": dict(params=9.24, hidden=3584, layers=42, inter=14336, kv=2048, vocab=256000, ctx=8192, license="gemma"),
    "google/gemma-2-27b": dict(params=27.2, hidden=4608, layers=46, inter=36864, kv=2048, vocab=256000, ctx=8192, license="gemma"),
    "microsoft/Phi-3.5-mini-instruct": dict(params=3.82, hidden=3072, layers=32, inter=8192, kv=3072, vocab=32064, ctx=131072, license="mit"),
    "microsoft/phi-4": dict(params=14.7, hidden=5120, layers=40, inter=17920, kv=1280, vocab=100352, ctx=16384, license="mit"),
}

PERMISSIVE = {"apache-2.0", "mit"}

# memory GB, dense bf16 TFLOPS (fp16 where no bf16), bf16 support, flash-attn 2 support, default $/GPU-hour
GPUS = {
    "T4": dict(mem=16, tflops=65, bf16=False, fa2=False, cost=0.35),
    "L4": dict(mem=24, tflops=121, bf16=True, fa2=True, cost=0.70),
    "A10G": dict(mem=24, tflops=70, bf16=True, fa2=True, cost=1.00),
    "RTX4090": dict(mem=24, tflops=82, bf16=True, fa2=True, cost=0.40),
    "A6000": dict(mem=48, tflops=155, bf16=True, fa2=True, cost=0.80),
    "L40S": dict(mem=48, tflops=362, bf16=True, fa2=True, cost=1.00),
    "A100-40GB": dict(mem=40, tflops=312, bf16=True, fa2=True, cost=1.20),
    "A100-80GB": dict(mem=80, tflops=312, bf16=True, fa2=True, cost=1.60),
    "H100-80GB": dict(mem=80, tflops=989, bf16=True, fa2=True, cost=2.50),
    "H200-141GB": dict(mem=141, tflops=989, bf16=True, fa2=True, cost=3.50),
    "B200-180GB": dict(mem=180, tflops=2250, bf16=True, fa2=True, cost=5.00),
    "MI300X-192GB": dict(mem=192, tflops=1307, bf16=True, fa2=True, cost=2.50),
}


def model_arch(cfg: dict) -> dict:
    """Architecture for the configured base model (preset or custom)."""
    key = cfg.get("base_model", "meta-llama/Llama-3.1-8B")
    if key in MODELS:
        return dict(MODELS[key], id=key)
    def num(k, d):
        try:
            return float(cfg.get(k) or d)
        except (TypeError, ValueError):
            return d
    hidden = int(num("custom_hidden", 4096))
    return dict(
        id=cfg.get("custom_model_id") or "custom",
        params=num("custom_params_b", 7.0),
        hidden=hidden,
        layers=int(num("custom_layers", 32)),
        inter=int(num("custom_inter", hidden * 3.5)),
        kv=int(num("custom_kv_dim", hidden // 4)),
        vocab=int(num("custom_vocab", 128000)),
        ctx=int(num("custom_ctx", 32768)),
        license="unknown",
    )


def gpu_spec(cfg: dict) -> dict:
    g = dict(GPUS.get(cfg.get("gpu_type", "A100-80GB"), GPUS["A100-80GB"]))
    try:
        if cfg.get("gpu_hourly_cost") not in (None, ""):
            g["cost"] = float(cfg["gpu_hourly_cost"])
    except (TypeError, ValueError):
        pass
    return g
