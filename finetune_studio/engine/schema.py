"""The full fine-tuning lifecycle as a declarative schema.

The UI renders every stage, section and field from this file, so adding an option here
is enough to make it appear in the app. Field keys form one flat namespace: the project
config is a flat dict {key: value}.

Field attributes
  key, label, type   select | multiselect | number | int | text | textarea | toggle | slider
  options            [(value, label, hint?)] for select / multiselect / slider
  default            default value
  help               tooltip text
  adv                True -> shown only in "Expert" mode
  show               {other_key: [values]} -> visible only when every condition matches
  min / max / step   numeric bounds; log=True renders the number in scientific notation
"""

from .catalog import GPUS, MODELS


def F(key, label, type_, default=None, help="", options=None, adv=False, show=None, **kw):
    f = dict(key=key, label=label, type=type_, default=default, help=help, adv=adv)
    if options is not None:
        f["options"] = [
            dict(value=o[0], label=o[1], hint=o[2] if len(o) > 2 else "")
            if isinstance(o, (tuple, list)) else dict(value=o, label=str(o), hint="")
            for o in options
        ]
    if show:
        f["show"] = show
    f.update(kw)
    return f


def S(title, fields, show=None, desc=""):
    s = dict(title=title, desc=desc, fields=fields)
    if show:
        s["show"] = show
    return s


LORA_LIKE = ["lora", "qlora", "dora", "adalora"]
PREF = ["dpo", "orpo", "simpo", "kto", "cpo"]
ONLINE = ["ppo", "grpo", "rloo"]

STAGES = [
    dict(id="objective", title="Objective", icon="target",
         summary="Frame the problem, constraints and what success means.",
         sections=[
             S("Problem framing", [
                 F("project_name", "Project name", "text", "my-finetune", "Used for run names, output dirs and the hub repo."),
                 F("task_type", "Task type", "select", "instruction", "Drives objective, data schema and metric recommendations.", [
                     ("instruction", "Instruction following / chat"),
                     ("classification", "Classification", "Sequence labels"),
                     ("extraction", "Information extraction / NER", "Structured output or token labels"),
                     ("summarization", "Summarization"),
                     ("code", "Code generation"),
                     ("reasoning", "Math / reasoning", "Verifiable answers"),
                     ("domain", "Domain adaptation", "Learn new vocabulary / knowledge"),
                     ("rag", "RAG-grounded QA", "Answer from retrieved context"),
                     ("tool_use", "Tool use / function calling"),
                     ("safety", "Safety / style alignment"),
                     ("embedding", "Embeddings / retrieval"),
                 ]),
                 F("modality", "Modality", "select", "text", "", [("text", "Text"), ("vision_language", "Vision-language"), ("audio_text", "Audio-text")]),
                 F("output_format", "Output format", "select", "free_text", "", [
                     ("free_text", "Free text"), ("json", "Structured JSON"), ("label", "Single label"),
                     ("spans", "Spans / tags"), ("code", "Code")]),
                 F("languages", "Languages", "text", "en", "Comma-separated ISO codes. Affects tokenizer choice and evaluation suites.", adv=True),
             ]),
             S("Constraints", [
                 F("priority", "Optimise for", "select", "balanced", "The advisor trades quality, cost and speed using this.", [
                     ("quality", "Max quality"), ("balanced", "Balanced"), ("cost", "Lowest cost"), ("speed", "Fastest iteration")]),
                 F("domain_shift", "Distance from pretraining data", "select", "medium", "How unlike general web text is your domain? Drives full-FT vs adapter choice.", [
                     ("low", "Low (style, format, tone)"), ("medium", "Medium (task skills)"), ("high", "High (new language, jargon, knowledge)")]),
                 F("preserve_general", "Must keep general skills", "toggle", True, "Penalises methods with high catastrophic-forgetting risk."),
                 F("deploy_target", "Deployment target", "select", "cloud_gpu", "", [
                     ("cloud_gpu", "Cloud GPU"), ("onprem_gpu", "On-prem GPU"), ("cpu_edge", "CPU / edge"),
                     ("mobile", "Mobile / on-device"), ("multi_tenant", "Multi-tenant adapter serving")]),
                 F("latency_p95_ms", "p95 latency budget (ms)", "int", 2000, "Per-request target for the deployed model.", min=0),
                 F("data_privacy", "Data sensitivity", "select", "internal", "", [
                     ("public", "Public"), ("internal", "Internal"), ("regulated", "Regulated / PII (HIPAA, GDPR)")]),
                 F("license_constraint", "Model licence", "select", "any", "Filters base models in the advisor.", [
                     ("any", "Any"), ("permissive", "Permissive only (Apache / MIT)")]),
             ]),
             S("Success criteria", [
                 F("primary_metric", "Primary metric", "select", "judge_winrate", "", [
                     ("accuracy", "Accuracy"), ("f1_macro", "Macro F1"), ("exact_match", "Exact match"),
                     ("rouge_l", "ROUGE-L"), ("pass_at_1", "pass@1"), ("judge_winrate", "LLM-judge win rate"),
                     ("perplexity", "Perplexity"), ("ndcg", "nDCG@10")]),
                 F("target_value", "Target value", "number", None, "Leave empty if unknown."),
                 F("baseline_value", "Baseline (current system)", "number", None, adv=True),
             ]),
         ]),

    dict(id="data", title="Data", icon="database",
         summary="Ingest, clean, format, split and tokenize the training data.",
         sections=[
             S("Source", [
                 F("data_source", "Source", "select", "local", "", [
                     ("local", "Local file"), ("hf_hub", "Hugging Face Hub"), ("object_store", "S3 / GCS / Azure Blob"),
                     ("warehouse", "Warehouse (BigQuery, Snowflake)"), ("synthetic", "Synthetic only")]),
                 F("data_path", "Path / dataset id", "text", "data/train.jsonl"),
                 F("data_kind", "What the data contains", "select", "sft", "The single most important input to the advisor.", [
                     ("sft", "Demonstrations", "prompt → ideal response"),
                     ("preference", "Preference pairs", "prompt, chosen, rejected"),
                     ("binary_feedback", "Binary feedback", "thumbs up / down per response"),
                     ("verifiable", "Prompts with checkable answers", "math, code, unit tests"),
                     ("raw_text", "Raw domain text", "documents, no labels"),
                     ("labels", "Class labels", "text → label"),
                 ]),
                 F("num_examples", "Number of examples", "int", 20000, "Profiling a file fills this in.", min=1),
                 F("avg_tokens", "Average tokens / example", "int", 512, min=1),
                 F("p95_tokens", "p95 tokens / example", "int", 1500, "Used to choose max sequence length.", min=1),
                 F("data_revision", "Revision / version pin", "text", "", "Commit sha, tag or DVC hash.", adv=True),
             ]),
             S("Schema & template", [
                 F("record_schema", "Record schema", "select", "messages", "", [
                     ("messages", "messages [{role, content}]"),
                     ("alpaca", "instruction / input / output"),
                     ("prompt_completion", "prompt / completion"),
                     ("preference", "prompt / chosen / rejected"),
                     ("kto", "prompt / completion / label"),
                     ("prompt_only", "prompt (+ answer for reward fn)"),
                     ("text", "text"),
                     ("text_label", "text / label"),
                 ]),
                 F("chat_template", "Chat template", "select", "model_default", "", [
                     ("model_default", "Model's own template"), ("chatml", "ChatML"), ("llama3", "Llama 3"),
                     ("mistral", "Mistral [INST]"), ("gemma", "Gemma"), ("alpaca", "Alpaca"), ("custom", "Custom Jinja")]),
                 F("custom_template", "Custom Jinja template", "textarea", "", show={"chat_template": ["custom"]}),
                 F("system_prompt", "Default system prompt", "textarea", "", "Injected when a record has no system turn.", adv=True),
                 F("train_on_completions", "Loss on completions only", "toggle", True, "Mask prompt tokens from the loss. Almost always better for SFT."),
                 F("mask_multi_turn", "Train on all assistant turns", "toggle", True, "If off, only the final assistant turn is trained.", adv=True),
             ]),
             S("Cleaning & filtering", [
                 F("dedup", "Deduplication", "select", "exact", "", [
                     ("none", "None"), ("exact", "Exact (hash)"), ("minhash", "Near-duplicate (MinHash LSH)"), ("semantic", "Semantic (embedding clusters)")]),
                 F("minhash_threshold", "Jaccard threshold", "slider", 0.8, show={"dedup": ["minhash"]}, min=0.5, max=0.99, step=0.01),
                 F("min_tokens", "Drop shorter than (tokens)", "int", 4, min=0),
                 F("max_tokens_filter", "Drop longer than (tokens)", "int", 0, "0 keeps everything (truncation applies instead).", min=0),
                 F("pii_scrub", "PII scrubbing", "select", "regex", "", [
                     ("none", "None"), ("regex", "Regex (emails, phones, IDs)"), ("presidio", "Presidio NER"), ("llm", "LLM redaction")]),
                 F("quality_filter", "Quality filter", "select", "heuristic", "", [
                     ("none", "None"), ("heuristic", "Heuristics (Gopher / C4 rules)"), ("perplexity", "Perplexity (KenLM)"),
                     ("classifier", "Quality classifier (FineWeb-Edu style)"), ("llm_judge", "LLM judge score")]),
                 F("quality_threshold", "Quality threshold", "slider", 0.5, show={"quality_filter": ["classifier", "llm_judge", "perplexity"]}, min=0, max=1, step=0.05),
                 F("toxicity_filter", "Toxicity filter", "toggle", False, adv=True),
                 F("lang_filter", "Language ID filter", "toggle", False, "fastText LID, keeps languages listed in Objective.", adv=True),
                 F("decontaminate", "Decontaminate vs eval sets", "toggle", True, "Remove n-gram overlap with benchmarks and your test split."),
                 F("decontam_ngram", "Overlap n-gram size", "int", 13, show={"decontaminate": [True]}, adv=True, min=5, max=50),
             ]),
             S("Augmentation", [
                 F("augmentation", "Augmentation", "multiselect", [], "", [
                     ("self_instruct", "Self-Instruct"), ("evol_instruct", "Evol-Instruct"), ("distill", "Teacher responses"),
                     ("rejection_sampling", "Rejection sampling (best-of-n)"), ("paraphrase", "Paraphrase"), ("backtranslation", "Back-translation"),
                     ("pref_synth", "Synthetic preference pairs (on-policy + judge)")]),
                 F("teacher_model", "Teacher model", "text", "", show={"augmentation": ["distill", "rejection_sampling", "pref_synth", "evol_instruct", "self_instruct"]}),
                 F("synth_ratio", "Max synthetic share", "slider", 0.3, show={"augmentation": ["distill", "rejection_sampling", "pref_synth", "evol_instruct", "self_instruct", "paraphrase", "backtranslation"]}, min=0, max=1, step=0.05),
             ]),
             S("Splits & sampling", [
                 F("val_ratio", "Validation share", "number", 0.05, min=0, max=0.5, step=0.01),
                 F("test_ratio", "Held-out test share", "number", 0.05, min=0, max=0.5, step=0.01),
                 F("split_strategy", "Split strategy", "select", "random", "", [
                     ("random", "Random"), ("stratified", "Stratified by label"), ("temporal", "Temporal (train past, test future)"),
                     ("group", "Grouped (by user / document — no leakage)")]),
                 F("split_group_key", "Group / time column", "text", "", show={"split_strategy": ["group", "temporal", "stratified"]}),
                 F("split_seed", "Split seed", "int", 42, adv=True),
                 F("data_mixing", "Dataset mixture", "textarea", "", "One per line: path_or_id weight. e.g. 'general_chat 0.2' to limit forgetting.", adv=True),
                 F("curriculum", "Curriculum", "select", "none", "", [("none", "None (shuffle)"), ("length", "Short → long"), ("difficulty", "Easy → hard")], adv=True),
             ]),
             S("Tokenization", [
                 F("max_seq_len", "Max sequence length", "int", 2048, "Activation memory grows linearly with this.", min=64),
                 F("packing", "Sequence packing", "select", "none", "", [
                     ("none", "None (pad)"), ("naive", "Concatenate (cross-attention leaks)"),
                     ("varlen", "Packing w/o contamination (position_ids + FA varlen)")]),
                 F("truncation_side", "Truncation side", "select", "right", "", [("right", "Right"), ("left", "Left (keep the end)")], adv=True),
                 F("padding_side", "Padding side", "select", "right", "", [("right", "Right"), ("left", "Left")], adv=True),
                 F("num_proc", "Preprocessing workers", "int", 8, adv=True, min=1),
             ]),
         ]),

    dict(id="model", title="Base model", icon="cpu",
         summary="Choose the starting checkpoint and how it is loaded.",
         sections=[
             S("Checkpoint", [
                 F("base_model", "Base model", "select", "meta-llama/Llama-3.1-8B", "Pick 'Custom' for any Hugging Face id.",
                   [(k, k.split("/")[-1], f"{v['params']}B · {v['license']}") for k, v in MODELS.items()] + [("custom", "Custom…")]),
                 F("custom_model_id", "Model id", "text", "", show={"base_model": ["custom"]}),
                 F("custom_params_b", "Parameters (B)", "number", 7.0, show={"base_model": ["custom"]}),
                 F("custom_hidden", "Hidden size", "int", 4096, show={"base_model": ["custom"]}),
                 F("custom_layers", "Layers", "int", 32, show={"base_model": ["custom"]}),
                 F("custom_inter", "MLP intermediate size", "int", 14336, show={"base_model": ["custom"]}, adv=True),
                 F("custom_kv_dim", "KV dim (kv_heads × head_dim)", "int", 1024, show={"base_model": ["custom"]}, adv=True),
                 F("custom_vocab", "Vocab size", "int", 128000, show={"base_model": ["custom"]}, adv=True),
                 F("model_variant", "Start from", "select", "instruct", "Instruct checkpoints need less data for chat tasks; base checkpoints are better for CPT.", [
                     ("base", "Base (pretrained)"), ("instruct", "Instruct / chat")]),
                 F("model_revision", "Revision", "text", "main", adv=True),
                 F("trust_remote_code", "trust_remote_code", "toggle", False, adv=True),
             ]),
             S("Architecture & kernels", [
                 F("attn_impl", "Attention kernel", "select", "flash_attention_2", "", [
                     ("flash_attention_2", "FlashAttention-2"), ("flash_attention_3", "FlashAttention-3 (Hopper)"),
                     ("sdpa", "PyTorch SDPA"), ("eager", "Eager")]),
                 F("rope_scaling", "RoPE scaling", "select", "none", "Extend context beyond pretraining length.", [
                     ("none", "None"), ("linear", "Linear (PI)"), ("dynamic", "Dynamic NTK"), ("yarn", "YaRN"), ("longrope", "LongRoPE")]),
                 F("rope_factor", "Scaling factor", "number", 2.0, show={"rope_scaling": ["linear", "dynamic", "yarn", "longrope"]}),
                 F("use_liger", "Liger kernels", "toggle", True, "Fused RMSNorm / RoPE / SwiGLU / cross-entropy. Cuts memory 20–60%."),
                 F("use_unsloth", "Unsloth", "toggle", False, "Fast single-GPU LoRA / QLoRA kernels.", adv=True),
                 F("pad_token", "Pad token", "select", "eos", "", [("eos", "Reuse EOS"), ("unk", "Reuse UNK"), ("new", "Add [PAD] (resizes embeddings)")], adv=True),
                 F("add_special_tokens", "Extra special tokens", "text", "", "Comma-separated. Embeddings and lm_head must then be trained.", adv=True),
             ]),
         ]),

    dict(id="technique", title="Technique", icon="sliders",
         summary="Full fine-tuning or a parameter-efficient method, and its settings.",
         sections=[
             S("Method", [
                 F("method", "Fine-tuning method", "select", "lora", "Use the Advisor for a ranked recommendation.", [
                     ("full", "Full fine-tuning", "all weights"),
                     ("freeze", "Partial (top-N layers)", "freeze the rest"),
                     ("lora", "LoRA", "low-rank adapters"),
                     ("qlora", "QLoRA", "LoRA on a 4-bit base"),
                     ("dora", "DoRA", "weight-decomposed LoRA"),
                     ("adalora", "AdaLoRA", "adaptive rank budget"),
                     ("vera", "VeRA", "shared random matrices, tiny"),
                     ("ia3", "IA³", "learned rescaling vectors"),
                     ("prefix", "Prefix tuning"),
                     ("prompt_tuning", "Prompt tuning", "soft prompt only"),
                     ("bitfit", "BitFit", "biases only"),
                     ("galore", "GaLore", "full-param, low-rank gradients"),
                 ]),
             ]),
             S("Adapter settings", show={"method": LORA_LIKE}, fields=[
                 F("lora_r", "Rank r", "slider", 16, "Capacity of the update. 8–64 covers most cases.",
                   [4, 8, 16, 32, 64, 128, 256]),
                 F("lora_alpha", "Alpha", "int", 32, "Scale = alpha / r (or alpha / √r with rsLoRA). Common: alpha = 2r.", min=1),
                 F("lora_dropout", "Dropout", "number", 0.05, min=0, max=0.5, step=0.01),
                 F("target_modules", "Target modules", "multiselect", ["all-linear"], "all-linear matches every Linear except lm_head.", [
                     ("all-linear", "all-linear"), ("q_proj", "q_proj"), ("k_proj", "k_proj"), ("v_proj", "v_proj"), ("o_proj", "o_proj"),
                     ("gate_proj", "gate_proj"), ("up_proj", "up_proj"), ("down_proj", "down_proj"),
                     ("embed_tokens", "embed_tokens"), ("lm_head", "lm_head")]),
                 F("lora_init", "Initialisation", "select", "default", "", [
                     ("default", "Kaiming / zeros (default)"), ("gaussian", "Gaussian"), ("pissa", "PiSSA (principal singular vectors)"),
                     ("olora", "OLoRA (QR)"), ("loftq", "LoftQ (quantization-aware)"), ("eva", "EVA (data-driven)")]),
                 F("use_rslora", "Rank-stabilised (rsLoRA)", "toggle", False, "Recommended for r ≥ 64."),
                 F("lora_bias", "Bias", "select", "none", "", ["none", "all", "lora_only"], adv=True),
                 F("loraplus_ratio", "LoRA+ lr ratio (B/A)", "number", 0, "0 = off. 16 is typical.", adv=True, min=0),
                 F("modules_to_save", "Also train fully", "text", "", "e.g. embed_tokens,lm_head when adding tokens.", adv=True),
                 F("layers_to_transform", "Only these layers", "text", "", "Comma-separated indices, empty = all.", adv=True),
                 F("adalora_init_r", "AdaLoRA initial r", "int", 12, show={"method": ["adalora"]}, adv=True),
                 F("adalora_target_r", "AdaLoRA target r", "int", 8, show={"method": ["adalora"]}, adv=True),
             ]),
             S("Quantized base", show={"method": ["qlora"]}, fields=[
                 F("quant_bits", "Bits", "select", 4, "", [(4, "4-bit"), (8, "8-bit")]),
                 F("quant_type", "4-bit type", "select", "nf4", "", [("nf4", "NF4"), ("fp4", "FP4")], show={"quant_bits": [4]}),
                 F("double_quant", "Double quantization", "toggle", True, "Saves ~0.4 bits/param."),
                 F("compute_dtype", "Compute dtype", "select", "bfloat16", "", ["bfloat16", "float16"]),
                 F("quant_storage", "Quant storage dtype", "select", "uint8", "Use bfloat16 to shard QLoRA with FSDP.", ["uint8", "bfloat16"], adv=True),
             ]),
             S("Soft prompts", show={"method": ["prefix", "prompt_tuning"]}, fields=[
                 F("num_virtual_tokens", "Virtual tokens", "int", 20, min=1),
                 F("prompt_init", "Initialisation", "select", "random", "", [("random", "Random"), ("text", "From text")], show={"method": ["prompt_tuning"]}),
                 F("prompt_init_text", "Init text", "text", "", show={"prompt_init": ["text"]}),
             ]),
             S("Partial freezing", show={"method": ["freeze"]}, fields=[
                 F("trainable_layers", "Trainable top layers", "int", 4, min=1),
                 F("train_embeddings", "Train embeddings", "toggle", False),
                 F("train_lm_head", "Train lm_head", "toggle", True),
             ]),
             S("GaLore", show={"method": ["galore"]}, fields=[
                 F("galore_rank", "Projection rank", "int", 128),
                 F("galore_update_gap", "Projection update gap", "int", 200),
                 F("galore_scale", "Scale", "number", 0.25),
             ]),
             S("VeRA", show={"method": ["vera"]}, fields=[
                 F("vera_r", "Rank", "int", 256),
             ]),
         ]),

    dict(id="alignment", title="Objective fn", icon="git-merge",
         summary="SFT, continued pretraining, preference optimisation, RL or distillation.",
         sections=[
             S("Training objective", [
                 F("objective", "Objective", "select", "sft", "", [
                     ("sft", "SFT", "supervised fine-tuning"),
                     ("cpt", "Continued pretraining", "causal LM on raw text"),
                     ("dpo", "DPO", "offline preference"),
                     ("orpo", "ORPO", "SFT + preference in one stage, no reference model"),
                     ("simpo", "SimPO", "reference-free, length-normalised"),
                     ("kto", "KTO", "unpaired binary feedback"),
                     ("cpo", "CPO"),
                     ("grpo", "GRPO", "online RL, group-relative, no critic"),
                     ("rloo", "RLOO", "REINFORCE leave-one-out"),
                     ("ppo", "PPO", "classic RLHF with critic"),
                     ("reward_model", "Reward model", "Bradley–Terry"),
                     ("distill", "Knowledge distillation", "logit / on-policy (GKD)"),
                     ("classifier", "Classification head", "AutoModelForSequenceClassification"),
                 ]),
                 F("neftune_alpha", "NEFTune noise α", "number", 0, "0 = off. 5 is typical for SFT.", adv=True, show={"objective": ["sft"]}, min=0),
                 F("label_smoothing", "Label smoothing", "number", 0, adv=True, min=0, max=0.5),
             ]),
             S("Preference optimisation", show={"objective": PREF}, fields=[
                 F("pref_beta", "β", "number", 0.1, "Strength of the implicit KL to the reference. Lower = moves further.", min=0, step=0.01),
                 F("dpo_loss_type", "Loss variant", "select", "sigmoid", "", [
                     ("sigmoid", "Sigmoid (DPO)"), ("ipo", "IPO"), ("hinge", "Hinge (SLiC)"), ("robust", "Robust DPO (noisy labels)"),
                     ("bco_pair", "BCO"), ("sppo_hard", "SPPO"), ("nca_pair", "NCA"), ("apo_zero", "APO-zero")], show={"objective": ["dpo"]}),
                 F("ref_model", "Reference model", "select", "peft_disabled", "", [
                     ("peft_disabled", "Base with adapter disabled (no extra memory)"), ("copy", "Frozen copy of policy"),
                     ("precompute", "Precomputed log-probs")], show={"objective": ["dpo", "kto"]}),
                 F("rpo_alpha", "NLL term weight (RPO)", "number", 0, "Adds SFT loss on chosen; helps prevent likelihood collapse.", adv=True, show={"objective": ["dpo"]}),
                 F("simpo_gamma", "Target margin γ", "number", 0.5, show={"objective": ["simpo"]}),
                 F("kto_desirable_weight", "Desirable weight", "number", 1.0, show={"objective": ["kto"]}),
                 F("kto_undesirable_weight", "Undesirable weight", "number", 1.0, show={"objective": ["kto"]}),
             ]),
             S("Online RL", show={"objective": ONLINE}, fields=[
                 F("reward_sources", "Rewards", "multiselect", ["accuracy", "format"], "", [
                     ("accuracy", "Answer correctness"), ("format", "Format / regex"), ("unit_tests", "Code execution / unit tests"),
                     ("reward_model", "Reward model"), ("llm_judge", "LLM judge"), ("length", "Length penalty")]),
                 F("reward_model_id", "Reward model id", "text", "", show={"reward_sources": ["reward_model"]}),
                 F("num_generations", "Group size (completions / prompt)", "int", 8, min=2),
                 F("max_completion_len", "Max completion length", "int", 1024),
                 F("gen_temperature", "Sampling temperature", "number", 1.0, min=0, max=2, step=0.05),
                 F("kl_coef", "KL coefficient β", "number", 0.0, "Recent GRPO recipes use 0 (no reference model)."),
                 F("clip_eps", "Clip ε", "number", 0.2),
                 F("grpo_loss_type", "Loss normalisation", "select", "dr_grpo", "", [
                     ("grpo", "GRPO (per-sequence)"), ("dr_grpo", "Dr. GRPO (unbiased)"), ("dapo", "DAPO (token-level)"), ("bnpo", "BNPO")], show={"objective": ["grpo"]}, adv=True),
                 F("use_vllm_gen", "Generate with vLLM", "toggle", True, "5–10× faster rollouts."),
                 F("vllm_mode", "vLLM mode", "select", "colocate", "", [("colocate", "Colocate (shares GPUs)"), ("server", "Separate server")], show={"use_vllm_gen": [True]}, adv=True),
                 F("ppo_epochs", "PPO epochs / batch", "int", 4, show={"objective": ["ppo"]}, adv=True),
                 F("vf_coef", "Value loss coef", "number", 0.1, show={"objective": ["ppo"]}, adv=True),
             ]),
             S("Distillation", show={"objective": ["distill"]}, fields=[
                 F("teacher_model_id", "Teacher model", "text", ""),
                 F("kd_loss", "Divergence", "select", "fkl", "", [("fkl", "Forward KL"), ("rkl", "Reverse KL"), ("jsd", "Generalised JSD (GKD)"), ("mse", "Logit MSE")]),
                 F("kd_temperature", "Temperature", "number", 2.0),
                 F("kd_alpha", "KD vs CE weight", "number", 0.5, min=0, max=1),
                 F("kd_on_policy", "On-policy (student samples)", "toggle", True),
             ]),
             S("Classification head", show={"objective": ["classifier"]}, fields=[
                 F("num_labels", "Number of labels", "int", 2, min=2),
                 F("problem_type", "Problem type", "select", "single_label", "", [("single_label", "Single-label"), ("multi_label", "Multi-label"), ("regression", "Regression")]),
                 F("class_weights", "Class weighting", "select", "none", "", [("none", "None"), ("balanced", "Inverse frequency"), ("focal", "Focal loss")]),
             ]),
         ]),

    dict(id="training", title="Hyperparameters", icon="activity",
         summary="Schedule, optimizer, batching, precision and checkpointing.",
         sections=[
             S("Schedule", [
                 F("epochs", "Epochs", "number", 2, min=0.1, step=0.5),
                 F("max_steps", "Max steps", "int", -1, "-1 = use epochs.", adv=True),
                 F("learning_rate", "Learning rate", "number", 2e-4, "Typical: LoRA 1e-4–3e-4 · full 5e-6–2e-5 · DPO 5e-7–5e-6.", log=True, min=0),
                 F("lr_scheduler", "LR schedule", "select", "cosine", "", [
                     ("cosine", "Cosine"), ("linear", "Linear"), ("constant_with_warmup", "Constant + warmup"),
                     ("cosine_with_min_lr", "Cosine to min LR"), ("cosine_with_restarts", "Cosine with restarts"),
                     ("warmup_stable_decay", "WSD (warmup–stable–decay)"), ("polynomial", "Polynomial"), ("inverse_sqrt", "Inverse sqrt"),
                     ("reduce_lr_on_plateau", "Reduce on plateau")]),
                 F("warmup_ratio", "Warmup ratio", "number", 0.03, min=0, max=0.5, step=0.01),
                 F("min_lr_ratio", "Min LR ratio", "number", 0.1, show={"lr_scheduler": ["cosine_with_min_lr", "warmup_stable_decay"]}),
                 F("num_cycles", "Restarts", "int", 2, show={"lr_scheduler": ["cosine_with_restarts"]}),
             ]),
             S("Optimizer", [
                 F("optimizer", "Optimizer", "select", "adamw_torch_fused", "", [
                     ("adamw_torch_fused", "AdamW (fused)"), ("adamw_torch", "AdamW"), ("adamw_8bit", "AdamW 8-bit (bnb)"),
                     ("paged_adamw_8bit", "Paged AdamW 8-bit"), ("paged_adamw_32bit", "Paged AdamW 32-bit"),
                     ("adafactor", "Adafactor"), ("lion_32bit", "Lion"), ("schedule_free_adamw", "Schedule-free AdamW"),
                     ("adamw_torch_4bit", "AdamW 4-bit (torchao)"), ("muon", "Muon (hidden weights) + AdamW"), ("sgd", "SGD")]),
                 F("weight_decay", "Weight decay", "number", 0.0, min=0, step=0.01),
                 F("max_grad_norm", "Gradient clip norm", "number", 1.0, min=0),
                 F("adam_beta1", "β1", "number", 0.9, adv=True),
                 F("adam_beta2", "β2", "number", 0.999, adv=True),
                 F("adam_eps", "ε", "number", 1e-8, adv=True, log=True),
                 F("embedding_lr", "Embedding LR", "number", None, "Separate LR for new/trained embeddings.", adv=True, log=True),
             ]),
             S("Batching", [
                 F("per_device_batch", "Micro-batch / GPU", "int", 4, min=1),
                 F("grad_accum", "Gradient accumulation", "int", 4, min=1),
                 F("group_by_length", "Group by length", "toggle", False, "Less padding, but biases loss curves.", adv=True),
                 F("dataloader_workers", "Dataloader workers", "int", 4, adv=True),
             ]),
             S("Precision & memory", [
                 F("precision", "Precision", "select", "bf16", "", [("bf16", "bf16 mixed"), ("fp16", "fp16 mixed (loss scaling)"), ("fp32", "fp32"), ("fp8", "FP8 (Transformer Engine / torchao, Hopper+)")]),
                 F("tf32", "Allow TF32 matmuls", "toggle", True, adv=True),
                 F("grad_checkpointing", "Gradient checkpointing", "select", "full", "Trades ~30% compute for a large activation-memory cut.", [
                     ("off", "Off"), ("full", "Full (every layer)"), ("offload", "Offloaded to CPU (Unsloth-style)")]),
                 F("torch_compile", "torch.compile", "toggle", False, adv=True),
             ]),
             S("Evaluation & checkpoints", [
                 F("eval_strategy", "Evaluate every", "select", "steps", "", [("steps", "N steps"), ("epoch", "Epoch"), ("no", "Never")]),
                 F("eval_steps", "Eval steps", "int", 200, show={"eval_strategy": ["steps"]}),
                 F("save_steps", "Save steps", "int", 200),
                 F("save_total_limit", "Keep last N checkpoints", "int", 3),
                 F("load_best", "Load best at end", "toggle", True),
                 F("early_stopping_patience", "Early-stopping patience (evals)", "int", 0, "0 = off.", min=0),
                 F("logging_steps", "Log every N steps", "int", 10, adv=True),
                 F("seed", "Seed", "int", 42),
                 F("full_determinism", "Full determinism", "toggle", False, "Slower; enables deterministic CUDA kernels.", adv=True),
             ]),
         ]),

    dict(id="compute", title="Compute", icon="server",
         summary="Hardware, parallelism strategy and where the job runs.",
         sections=[
             S("Hardware", [
                 F("gpu_type", "GPU", "select", "A100-80GB", "", [(k, k, f"{v['mem']} GB") for k, v in GPUS.items()]),
                 F("num_gpus", "GPUs per node", "int", 1, min=1, max=16),
                 F("num_nodes", "Nodes", "int", 1, min=1),
                 F("gpu_hourly_cost", "$ / GPU-hour", "number", None, "Empty = typical on-demand price."),
             ]),
             S("Parallelism", [
                 F("dist_strategy", "Strategy", "select", "auto", "", [
                     ("auto", "Auto (pick for me)"), ("single", "Single GPU"), ("ddp", "DDP"),
                     ("fsdp", "FSDP"), ("zero1", "DeepSpeed ZeRO-1"), ("zero2", "DeepSpeed ZeRO-2"),
                     ("zero3", "DeepSpeed ZeRO-3"), ("zero3_offload", "ZeRO-3 + CPU offload")]),
                 F("fsdp_sharding", "FSDP sharding", "select", "FULL_SHARD", "", ["FULL_SHARD", "SHARD_GRAD_OP", "HYBRID_SHARD", "NO_SHARD"], show={"dist_strategy": ["fsdp"]}),
                 F("fsdp_version", "FSDP version", "select", 2, "", [(1, "FSDP1"), (2, "FSDP2 (per-param DTensor)")], show={"dist_strategy": ["fsdp"]}, adv=True),
                 F("offload_optimizer", "Offload optimizer to CPU", "toggle", False, adv=True),
                 F("seq_parallel", "Sequence parallelism", "select", "none", "For very long contexts.", [("none", "None"), ("ring", "Ring attention"), ("ulysses", "DeepSpeed-Ulysses")], adv=True),
             ]),
             S("Orchestration", [
                 F("launcher", "Launcher", "select", "accelerate", "", ["accelerate", "torchrun", "deepspeed"]),
                 F("platform", "Platform", "select", "local", "", [
                     ("local", "Local / VM"), ("slurm", "SLURM"), ("k8s", "Kubernetes (PyTorchJob)"), ("ray", "Ray Train"),
                     ("sagemaker", "SageMaker"), ("vertex", "Vertex AI"), ("azureml", "Azure ML"), ("modal", "Modal")]),
                 F("spot", "Spot / preemptible", "toggle", False, "Cheaper; requires frequent checkpoints to remote storage."),
                 F("checkpoint_uri", "Remote checkpoint URI", "text", "", adv=True),
                 F("container_image", "Container image", "text", "", adv=True),
             ]),
         ]),

    dict(id="tracking", title="Tracking", icon="git-branch",
         summary="Experiment tracking, lineage and reproducibility.",
         sections=[
             S("Experiment tracking", [
                 F("tracker", "Tracker", "select", "wandb", "", [("wandb", "Weights & Biases"), ("mlflow", "MLflow"), ("tensorboard", "TensorBoard"), ("comet_ml", "Comet"), ("none", "None")]),
                 F("tracker_project", "Project", "text", "finetune"),
                 F("run_name", "Run name template", "text", "{project}-{method}-r{lora_r}-lr{learning_rate}"),
                 F("log_model", "Log model artifacts", "select", "end", "", [("false", "No"), ("checkpoint", "Every checkpoint"), ("end", "Final only")], adv=True),
                 F("watch_grads", "Log gradient histograms", "toggle", False, adv=True),
             ]),
             S("Lineage & registry", [
                 F("push_to_hub", "Push to Hugging Face Hub", "toggle", False),
                 F("hub_model_id", "Hub repo", "text", "", show={"push_to_hub": [True]}),
                 F("hub_private", "Private repo", "toggle", True, show={"push_to_hub": [True]}),
                 F("data_versioning", "Data versioning", "select", "hf_revision", "", [("none", "None"), ("dvc", "DVC"), ("lakefs", "lakeFS"), ("hf_revision", "HF revision pin"), ("delta", "Delta / Iceberg snapshot")]),
                 F("record_env", "Record env (git sha, pip freeze, nvidia-smi)", "toggle", True),
             ]),
         ]),

    dict(id="ft_testing", title="Fine-tune testing", icon="flask",
         summary="Tests specific to fine-tuning: before, during and after the training run, tailored to your objective and technique.",
         sections=[
             S("Pre-training sanity checks", desc="Run in minutes on one GPU before the expensive job (ft_checks.py). Most failed fine-tunes are pipeline bugs these catch.", fields=[
                 F("preflight_checks", "Checks", "multiselect",
                   ["template_render", "loss_mask", "truncation", "trainable_audit", "identity_init", "initial_loss", "overfit_batch", "throughput"], "", [
                     ("template_render", "Chat template renders & round-trips", "special tokens, EOS after each target"),
                     ("loss_mask", "Loss mask covers only target tokens", "no prompt/system tokens in the loss"),
                     ("truncation", "Truncation & length audit", "share of examples cut at max_seq_len"),
                     ("trainable_audit", "Trainable-parameter audit", "the intended modules — and only those — train"),
                     ("identity_init", "Zero-init identity", "adapter model == base model at step 0"),
                     ("initial_loss", "Initial-loss sanity", "≈ base perplexity, far below ln(vocab)"),
                     ("overfit_batch", "Overfit one batch", "loss → ~0 proves gradients flow end-to-end"),
                     ("lr_range", "LR range test", "loss vs exponentially rising LR"),
                     ("determinism", "Determinism", "same seed → same loss trajectory"),
                     ("throughput", "Throughput & memory smoke", "tokens/s and peak memory vs estimate")]),
                 F("overfit_steps", "Overfit-batch steps", "int", 60, show={"preflight_checks": ["overfit_batch"]}, adv=True, min=5),
                 F("lr_range_bounds", "LR range (min,max)", "text", "1e-7,1e-2", show={"preflight_checks": ["lr_range"]}, adv=True),
                 F("max_truncation", "Max truncated share", "number", 0.05, show={"preflight_checks": ["truncation"]}, min=0, max=1, step=0.01),
                 F("preflight_block", "Block training if a check fails", "toggle", True, "launch.sh runs ft_checks.py first and stops on failure."),
             ]),
             S("In-training monitors", desc="Callbacks in train.py that watch fine-tuning failure modes live and can stop the run.", fields=[
                 F("monitors_train", "Monitors", "multiselect", ["nan_guard", "loss_spike", "grad_spike", "gen_gap", "sample_gens"], "", [
                     ("nan_guard", "NaN / inf guard"), ("loss_spike", "Loss spikes"), ("grad_spike", "Gradient-norm spikes"),
                     ("gen_gap", "Train/val divergence (overfitting)"), ("lr_check", "LR schedule sanity"), ("sample_gens", "Sample generations at each eval"),
                     ("dpo_displacement", "DPO: likelihood displacement", "chosen log-prob falling"),
                     ("dpo_reward_acc", "DPO: reward accuracy & margins"),
                     ("rl_reward_hacking", "RL: reward hacking", "reward ↑ with length / format drift"),
                     ("rl_entropy", "RL: entropy collapse"), ("rl_kl", "RL: KL blow-up"),
                     ("rl_zero_std", "RL: zero-variance groups", "no learning signal")]),
                 F("spike_factor", "Spike threshold (× running mean)", "number", 3.0, adv=True, min=1.5),
                 F("monitor_action", "On a critical alert", "select", "stop", "", [("warn", "Warn only"), ("stop", "Save & stop")]),
                 F("sample_prompts_n", "Sample prompts per eval", "int", 4, show={"monitors_train": ["sample_gens"]}, adv=True, min=1),
             ]),
             S("Checkpoint selection", [
                 F("ckpt_selection", "Pick the final model by", "select", "best_task_metric", "Validation loss often disagrees with task quality, especially for preference / RL objectives.", [
                     ("final", "Last checkpoint"), ("best_val_loss", "Best validation loss"),
                     ("best_task_metric", "Best validation task metric (generate & score)"), ("soup", "Average of last-k checkpoints (weight soup)")]),
                 F("ckpt_eval_n", "Validation items per checkpoint", "int", 200, show={"ckpt_selection": ["best_task_metric"]}, min=20),
                 F("soup_k", "Checkpoints to average", "int", 3, show={"ckpt_selection": ["soup"]}, min=2),
             ]),
             S("Search, ablation & data scaling", desc="Run by sweep.py. Selection uses the validation split only; the test split is touched once, at the end.", fields=[
                 F("hpo", "Hyperparameter search", "toggle", False),
                 F("hpo_method", "Search", "select", "asha", "", [("tpe", "Bayesian (Optuna TPE)"), ("random", "Random"), ("grid", "Grid"), ("asha", "Successive halving (ASHA-style)")], show={"hpo": [True]}),
                 F("hpo_trials", "Trials", "int", 16, show={"hpo": [True]}, min=2),
                 F("hpo_space", "Search over", "multiselect", ["learning_rate", "lora_r"], "", [
                     ("learning_rate", "Learning rate"), ("lora_r", "LoRA rank"), ("lora_alpha", "LoRA alpha"), ("lora_dropout", "LoRA dropout"),
                     ("epochs", "Epochs"), ("warmup_ratio", "Warmup"), ("weight_decay", "Weight decay"), ("beta", "β (preference / KL)")], show={"hpo": [True]}),
                 F("learning_curve", "Learning curve (data scaling)", "toggle", False, "Train on growing data fractions: tells you whether more data or a better model is the next lever."),
                 F("lc_fractions", "Fractions", "text", "0.1,0.25,0.5,1.0", show={"learning_curve": [True]}),
                 F("data_ablation", "Leave-one-source-out ablation", "toggle", False, "Uses the dataset mixture from the Data step.", adv=True),
                 F("label_noise_audit", "Noisy-label audit", "toggle", False, "Ranks training examples by loss under the trained model for human review."),
             ]),
             S("Fine-tuning diagnostics", desc="Post-training checks for the side effects fine-tuning is known to cause (ft_diagnostics.py).", fields=[
                 F("ft_diagnostics", "Diagnostics", "multiselect", ["generalization_gap", "safety_erosion", "stop_behavior", "length_drift", "diversity"], "", [
                     ("generalization_gap", "Train vs held-out gap", "memorisation"),
                     ("safety_erosion", "Safety-alignment erosion vs base", "fine-tuning can undo refusals"),
                     ("stop_behavior", "Stops correctly", "EOS vs max-length hits"),
                     ("length_drift", "Response-length drift", "vs training targets and base"),
                     ("diversity", "Mode collapse", "distinct-n, self-BLEU vs base"),
                     ("calibration_drift", "Calibration drift", "ECE vs base"),
                     ("template_robustness", "Unseen system prompts / templates"),
                     ("merge_equivalence", "Merged == adapter", "logit check"),
                     ("sycophancy", "Sycophancy", "flips answer under user pushback"),
                     ("knowledge_probes", "Injected-knowledge probes", "paraphrase & reversal"),
                     ("unknown_facts", "Hallucination on new facts", "known vs unknown to the base")]),
                 F("probes_path", "Knowledge probes", "text", "tests/knowledge_probes.jsonl", show={"ft_diagnostics": ["knowledge_probes", "unknown_facts"]}),
                 F("max_safety_erosion", "Max rise in harmful compliance", "number", 0.02, show={"ft_diagnostics": ["safety_erosion"]}, min=0, max=1, step=0.01),
                 F("max_gen_gap", "Max train − held-out gap", "number", 0.10, show={"ft_diagnostics": ["generalization_gap"]}, min=0, max=1, step=0.01),
                 F("min_stop_rate", "Min clean-stop rate", "number", 0.98, show={"ft_diagnostics": ["stop_behavior"]}, min=0, max=1, step=0.01),
                 F("max_length_ratio", "Max length ratio vs targets", "number", 1.5, show={"ft_diagnostics": ["length_drift"]}, min=1),
                 F("merge_tolerance", "Merge logit tolerance", "number", 0.05, show={"ft_diagnostics": ["merge_equivalence"]}, adv=True),
             ]),
             S("Objective-specific tests", desc="What 'working' means differs per training objective.", fields=[
                 F("objective_tests", "Tests", "multiselect", ["sft_heldout_ppl"], "The Advisor picks the ones matching your objective.", [
                     ("sft_heldout_ppl", "SFT: held-out completion perplexity"),
                     ("pref_accuracy", "Preference: held-out implicit-reward accuracy"),
                     ("lc_winrate", "Preference: length-controlled win rate"),
                     ("rm_accuracy", "Reward model: pairwise accuracy & calibration"),
                     ("rl_passk", "RL: pass@k curve vs base"),
                     ("rl_hack_probes", "RL: reward-hacking probes"),
                     ("distill_agreement", "Distillation: student–teacher agreement"),
                     ("cpt_ppl", "CPT: domain vs general perplexity"),
                     ("cls_report", "Classifier: confusion matrix, per-class P/R, threshold tuning")]),
                 F("passk_max", "Max k for pass@k", "int", 16, show={"objective_tests": ["rl_passk"]}, min=2),
                 F("general_ppl_path", "General-text sample (CPT)", "text", "", "JSONL of general text; empty = WikiText-2.", show={"objective_tests": ["cpt_ppl"]}, adv=True),
                 F("min_pref_accuracy", "Min preference accuracy", "number", 0.6, show={"objective_tests": ["pref_accuracy", "rm_accuracy"]}),
             ]),
             S("Technique-specific tests", desc="Checks tied to how the weights were changed.", fields=[
                 F("technique_tests", "Tests", "multiselect", ["frozen_checksum"], "The Advisor picks the ones matching your method.", [
                     ("rank_ablation", "LoRA: rank ablation", "r ∈ {8, 16, 32, 64}"),
                     ("adapter_norms", "Adapter update norms ‖BA‖ per layer"),
                     ("qlora_bf16_merge", "QLoRA: merge onto bf16 base & re-test"),
                     ("frozen_checksum", "Frozen weights unchanged (checksum)"),
                     ("weight_drift", "Full FT: weight drift ‖ΔW‖/‖W‖ per layer"),
                     ("prompt_seed_sensitivity", "Prompt tuning: init / seed sensitivity"),
                     ("adapter_isolation", "Multi-LoRA: adapter isolation & hot-swap")]),
             ]),
         ]),

    dict(id="evaluation", title="Evaluation & testing", icon="check-circle",
         summary="Test sets, metrics, behavioural, robustness, judge, human, grounding, safety, statistics, load and release gates.",
         sections=[
             S("Test sets", desc="Score on more than one distribution: in-distribution alone overstates real-world quality.", fields=[
                 F("test_sets", "Test sets", "multiselect", ["in_dist", "golden"], "Each set is scored separately and reported side by side.", [
                     ("in_dist", "Held-out split (in-distribution)"), ("ood", "Out-of-distribution set"), ("golden", "Golden regression suite"),
                     ("adversarial", "Adversarial / hard cases"), ("production_sample", "Sampled production traffic"), ("temporal", "Newer data than training (temporal)")]),
                 F("ood_path", "OOD set path", "text", "data/ood.jsonl", show={"test_sets": ["ood"]}),
                 F("golden_path", "Golden suite path", "text", "tests/golden.jsonl", "Curated cases with assertions; an example file is generated.", show={"test_sets": ["golden"]}),
                 F("adversarial_path", "Adversarial set path", "text", "data/adversarial.jsonl", show={"test_sets": ["adversarial"]}),
                 F("prod_sample_path", "Production sample path", "text", "data/prod_sample.jsonl", show={"test_sets": ["production_sample"]}),
                 F("temporal_path", "Temporal set path", "text", "data/recent.jsonl", show={"test_sets": ["temporal"]}),
                 F("slice_by", "Slice metrics by", "text", "", "Comma-separated record fields (e.g. language,category). Finds where the model fails.", adv=True),
             ]),
             S("Harness & benchmarks", [
                 F("eval_harness", "Harness", "select", "lm_eval", "", [("lm_eval", "lm-evaluation-harness"), ("lighteval", "LightEval"), ("custom", "Custom script only")]),
                 F("benchmarks", "Benchmarks", "multiselect", ["mmlu", "ifeval"], "", [
                     ("mmlu", "MMLU"), ("mmlu_pro", "MMLU-Pro"), ("gpqa", "GPQA"), ("bbh", "BBH"), ("gsm8k", "GSM8K"), ("math", "MATH"),
                     ("humaneval", "HumanEval"), ("mbpp", "MBPP"), ("arc_challenge", "ARC-C"), ("hellaswag", "HellaSwag"),
                     ("truthfulqa", "TruthfulQA"), ("ifeval", "IFEval"), ("mt_bench", "MT-Bench"), ("alpaca_eval", "AlpacaEval 2 (LC)"), ("arena_hard", "Arena-Hard")]),
                 F("eval_few_shot", "Few-shot", "int", 0, min=0),
                 F("eval_limit", "Limit examples / task", "int", 0, "0 = all.", adv=True),
             ]),
             S("Task metrics", [
                 F("task_metrics", "Metrics on your test sets", "multiselect", ["exact_match", "rouge_l"], "", [
                     ("accuracy", "Accuracy"), ("f1_macro", "F1 macro"), ("f1_micro", "F1 micro"), ("exact_match", "Exact match"), ("token_f1", "Token F1"),
                     ("rouge_l", "ROUGE-L"), ("bleu", "BLEU"), ("chrf", "chrF"), ("bertscore", "BERTScore"),
                     ("pass_at_k", "pass@k"), ("json_valid", "JSON validity"), ("perplexity", "Perplexity"), ("calibration", "ECE (calibration)")]),
             ]),
             S("Behavioural tests (CheckList)", desc="Unit tests for model behaviour — the regression suite that catches what averages hide.", show={"test_sets": ["golden"]}, fields=[
                 F("behavioral_tests", "Test types", "multiselect", ["mft", "inv", "dir"], "", [
                     ("mft", "Minimum functionality", "capability unit tests"), ("inv", "Invariance", "perturbation must not change the answer"),
                     ("dir", "Directional", "a change must move the output a known way")]),
                 F("assertion_types", "Assertions", "multiselect", ["exact", "contains", "regex", "json_schema"], "", [
                     ("exact", "Exact"), ("contains", "Contains"), ("not_contains", "Does not contain"), ("regex", "Regex"),
                     ("json_schema", "JSON schema"), ("numeric", "Numeric ± tolerance"), ("tool_call", "Tool call match"), ("judge_rubric", "Judge rubric")]),
                 F("min_behavioral_pass", "Required pass rate", "number", 0.95, min=0, max=1, step=0.01),
             ]),
             S("Robustness", [
                 F("perturbations", "Perturbations", "multiselect", ["typos", "case", "whitespace", "template"], "Applied to the in-distribution set; reports the metric drop and answer consistency.", [
                     ("typos", "Typos"), ("case", "Casing"), ("whitespace", "Whitespace / formatting"), ("template", "Prompt template variants"),
                     ("distractor", "Irrelevant context"), ("unicode", "Homoglyphs / unicode"), ("paraphrase", "Paraphrase (LLM)"), ("translate", "Translation (LLM)")]),
                 F("max_robustness_drop", "Max allowed metric drop", "number", 0.05, min=0, max=1, step=0.01),
                 F("robustness_n", "Examples to perturb", "int", 300, min=10, adv=True),
                 F("long_context_test", "Long-context retrieval (needle)", "toggle", False, "Plants a fact at several depths and context lengths.", adv=True),
             ]),
             S("LLM-as-judge", [
                 F("judge_enabled", "Use an LLM judge", "toggle", True),
                 F("judge_model", "Judge model", "text", "", "Any OpenAI-compatible endpoint (JUDGE_BASE_URL / JUDGE_API_KEY).", show={"judge_enabled": [True]}),
                 F("judge_mode", "Mode", "select", "pairwise_base", "", [("single", "Single answer, rubric score"), ("pairwise_base", "Pairwise vs baselines"), ("pairwise_ref", "Pairwise vs reference")], show={"judge_enabled": [True]}),
                 F("position_swap", "Swap positions (de-bias)", "toggle", True, show={"judge_enabled": [True]}),
                 F("judge_calibration", "Calibrate against human labels", "toggle", True, "Reports judge–human agreement (Cohen's κ). A judge you have not validated is an opinion.", show={"judge_enabled": [True]}),
                 F("judge_ensemble", "Jury of judges", "toggle", False, "Several judge models, majority vote — reduces self-preference bias.", show={"judge_enabled": [True]}, adv=True),
                 F("judge_rubric", "Rubric", "textarea", "", show={"judge_enabled": [True]}, adv=True),
             ]),
             S("Human evaluation", [
                 F("human_eval", "Run human evaluation", "toggle", False, "Exports a blinded, randomised annotation pack and analyses returned labels."),
                 F("human_protocol", "Protocol", "select", "sbs", "", [("sbs", "Blind side-by-side"), ("likert", "Likert rubric"), ("ranking", "N-way ranking"), ("error_taxonomy", "Error taxonomy annotation")], show={"human_eval": [True]}),
                 F("human_n", "Items", "int", 300, "Use the power analysis in the inspector to size this.", show={"human_eval": [True]}, min=10),
                 F("annotators_per_item", "Annotators per item", "int", 3, show={"human_eval": [True]}, min=1),
                 F("iaa_metric", "Agreement metric", "select", "fleiss_kappa", "", [("cohen_kappa", "Cohen's κ (2 raters)"), ("fleiss_kappa", "Fleiss' κ"), ("krippendorff_alpha", "Krippendorff's α")], show={"human_eval": [True]}, adv=True),
                 F("min_iaa", "Min agreement to trust results", "number", 0.6, show={"human_eval": [True]}, adv=True),
             ]),
             S("Hallucination & grounding", [
                 F("grounding_methods", "Methods", "multiselect", [], "", [
                     ("faithfulness", "Faithfulness to context"), ("answer_relevancy", "Answer relevancy"), ("context_precision", "Context precision"),
                     ("citation_accuracy", "Citation accuracy"), ("factscore", "Atomic-fact precision (FActScore)"), ("selfcheck", "Self-consistency (SelfCheckGPT)")]),
                 F("grounding_backend", "Backend", "select", "builtin", "", [("builtin", "Built-in heuristics"), ("ragas", "RAGAS"), ("judge", "LLM judge")], adv=True),
             ]),
             S("Safety, security & privacy", [
                 F("safety_suites", "Suites", "multiselect", [], "", [
                     ("harmbench", "Jailbreaks (HarmBench)"), ("xstest", "Over-refusal (XSTest)"), ("toxicity", "Toxicity (RealToxicityPrompts)"), ("bbq", "Bias (BBQ)"),
                     ("prompt_injection", "Prompt injection"), ("pii_leak", "PII leakage"), ("custom_safety", "Custom safety set")]),
                 F("red_team_tool", "Automated red teaming", "select", "none", "", [("none", "None"), ("garak", "garak"), ("pyrit", "PyRIT"), ("promptfoo", "promptfoo")]),
                 F("memorization_test", "Memorisation / regurgitation test", "toggle", False, "Prompts with training-example prefixes and measures verbatim continuation."),
                 F("safety_path", "Custom safety set", "text", "tests/safety.jsonl", "{prompt, should_refuse} records; an example is generated.", show={"safety_suites": ["custom_safety", "prompt_injection"]}),
             ]),
             S("Regression & comparisons", desc="Always compare: a fine-tune only earns its cost if it beats the alternatives.", fields=[
                 F("compare_against", "Compare against", "multiselect", ["base", "prompted_baseline"], "", [
                     ("base", "Base model"), ("prompted_baseline", "Prompt-engineered baseline (no fine-tune)"),
                     ("champion", "Current production model"), ("prev_run", "Previous fine-tune run")]),
                 F("champion_model", "Production model id / path", "text", "", show={"compare_against": ["champion"]}),
                 F("prev_run_path", "Previous run path", "text", "", show={"compare_against": ["prev_run"]}),
                 F("forgetting_check", "General-skills regression vs base", "toggle", True, "Runs the same benchmarks on the base to catch catastrophic forgetting."),
                 F("quant_degradation_check", "Re-test the exported / quantized model", "toggle", True, "Quantization can silently cost points; test what you ship."),
                 F("overfit_check", "Overfitting diagnostics", "toggle", True, "Train/val loss gap and train-set memorisation.", adv=True),
             ]),
             S("Statistical rigor", [
                 F("sig_test", "Significance test", "select", "paired_bootstrap", "Paired tests: every model answers the same items.", [
                     ("paired_bootstrap", "Paired bootstrap"), ("mcnemar", "McNemar (binary outcomes)"), ("wilcoxon", "Wilcoxon signed-rank"),
                     ("permutation", "Paired permutation"), ("none", "None")]),
                 F("sig_alpha", "α", "number", 0.05, min=0.001, max=0.2),
                 F("mde", "Minimum effect worth detecting", "number", 0.03, "Absolute difference in the primary metric. Drives the power analysis.", min=0.001, max=0.5),
                 F("train_seeds", "Training seeds", "int", 1, "Repeat training with different seeds to measure run-to-run variance.", min=1, max=10),
                 F("bootstrap_ci", "Bootstrap 95% CIs", "toggle", True),
                 F("bootstrap_samples", "Bootstrap resamples", "int", 1000, show={"bootstrap_ci": [True]}, adv=True),
                 F("multiple_comparisons", "Multiple-comparison correction", "select", "holm", "", [("none", "None"), ("holm", "Holm–Bonferroni"), ("bh", "Benjamini–Hochberg (FDR)")], adv=True),
             ]),
             S("Decoding for eval", [
                 F("eval_temperature", "Temperature", "number", 0.0, min=0, max=2),
                 F("eval_top_p", "top-p", "number", 1.0, min=0, max=1),
                 F("eval_max_new_tokens", "Max new tokens", "int", 1024),
                 F("eval_num_samples", "Samples / prompt", "int", 1, "> 1 for pass@k or self-consistency.", min=1),
             ]),
             S("Performance & load", [
                 F("load_test", "Load test the served model", "toggle", True),
                 F("load_tool", "Tool", "select", "vllm_bench", "", [("vllm_bench", "vllm bench serve"), ("genai_perf", "NVIDIA GenAI-Perf"), ("locust", "Locust"), ("k6", "k6")], show={"load_test": [True]}),
                 F("load_concurrency", "Concurrency", "int", 32, show={"load_test": [True]}, min=1),
                 F("load_metrics", "Measure", "multiselect", ["ttft", "p95_latency", "throughput", "error_rate"], "", [
                     ("ttft", "Time to first token"), ("p50_latency", "p50 latency"), ("p95_latency", "p95 latency"), ("throughput", "Tokens / s"),
                     ("error_rate", "Error rate"), ("cost_per_1k", "Cost / 1k requests")], show={"load_test": [True]}),
             ]),
             S("Release gates", desc="Acceptance criteria checked automatically; the suite exits non-zero on failure so CI can block the release.", fields=[
                 F("gate_primary", "Primary metric ≥ target", "toggle", True, "Uses the target set on the Objective step."),
                 F("gate_require_significance", "Improvement must be significant", "toggle", True),
                 F("gate_max_regression", "Max general-benchmark drop", "number", 0.02, min=0, max=1, step=0.005),
                 F("gate_min_winrate", "Min judge win rate vs baselines", "number", 0.55, min=0, max=1, step=0.01),
                 F("gate_min_safety", "Min safety pass rate", "number", 0.98, min=0, max=1, step=0.005),
                 F("gate_max_overrefusal", "Max over-refusal rate", "number", 0.05, min=0, max=1, step=0.01),
                 F("gate_max_quant_drop", "Max drop after quantization", "number", 0.01, min=0, max=1, step=0.005),
                 F("gate_max_p95_ms", "Max p95 latency (ms)", "int", None, "Empty = latency budget from Objective."),
                 F("gate_block", "Fail CI when a gate fails", "toggle", True),
             ]),
         ]),

    dict(id="export", title="Optimize & export", icon="package",
         summary="Merge, quantize and package the model for serving.",
         sections=[
             S("Packaging", [
                 F("merge_adapters", "Merge adapters into base", "toggle", True, "Off keeps a small adapter for multi-LoRA serving."),
                 F("export_dtype", "Export dtype", "select", "bfloat16", "", ["bfloat16", "float16", "float32"]),
                 F("export_formats", "Formats", "multiselect", ["safetensors"], "", [("safetensors", "safetensors"), ("onnx", "ONNX"), ("tensorrt_llm", "TensorRT-LLM engine"), ("mlx", "MLX"), ("coreml", "Core ML"), ("openvino", "OpenVINO")]),
                 F("model_card", "Generate model card", "toggle", True),
             ]),
             S("Post-training quantization", [
                 F("ptq_method", "Method", "select", "none", "", [("none", "None"), ("awq", "AWQ"), ("gptq", "GPTQ"), ("gguf", "GGUF (llama.cpp)"), ("fp8", "FP8 (W8A8)"), ("bnb", "bitsandbytes"), ("hqq", "HQQ")]),
                 F("gguf_quant", "GGUF type", "select", "Q4_K_M", "", ["Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "F16"], show={"ptq_method": ["gguf"]}),
                 F("ptq_bits", "Weight bits", "select", 4, "", [(4, "4"), (8, "8")], show={"ptq_method": ["awq", "gptq", "hqq"]}),
                 F("ptq_group_size", "Group size", "int", 128, show={"ptq_method": ["awq", "gptq", "hqq"]}),
                 F("calib_samples", "Calibration samples", "int", 512, show={"ptq_method": ["awq", "gptq", "fp8"]}, adv=True),
                 F("pruning", "Pruning", "select", "none", "", [("none", "None"), ("wanda", "Wanda"), ("sparsegpt", "SparseGPT"), ("sparse24", "2:4 structured")], adv=True),
             ]),
         ]),

    dict(id="deploy", title="Deploy & monitor", icon="radio",
         summary="Serve, roll out safely, monitor and close the retraining loop.",
         sections=[
             S("Serving", [
                 F("serving_engine", "Engine", "select", "vllm", "", [("vllm", "vLLM"), ("sglang", "SGLang"), ("tgi", "TGI"), ("trtllm", "TensorRT-LLM / Triton"), ("llamacpp", "llama.cpp"), ("ollama", "Ollama")]),
                 F("multi_lora", "Multi-LoRA serving", "toggle", False, "Serve many adapters on one base."),
                 F("serve_max_len", "Max model length", "int", 8192),
                 F("serve_tp", "Tensor parallel size", "int", 1, min=1),
                 F("kv_cache_dtype", "KV-cache dtype", "select", "auto", "", ["auto", "fp8"], adv=True),
                 F("spec_decoding", "Speculative decoding", "select", "none", "", [("none", "None"), ("ngram", "n-gram lookup"), ("draft", "Draft model"), ("eagle", "EAGLE-3")], adv=True),
                 F("guardrails", "Guardrails", "multiselect", [], "", [("llama_guard", "Llama Guard"), ("nemo", "NeMo Guardrails"), ("json_schema", "JSON-schema constrained decoding"), ("pii_out", "Output PII filter")]),
             ]),
             S("Rollout", [
                 F("rollout", "Strategy", "select", "shadow", "", [("shadow", "Shadow"), ("canary", "Canary"), ("ab", "A/B test"), ("blue_green", "Blue-green"), ("direct", "Direct")]),
                 F("canary_pct", "Canary traffic %", "int", 5, show={"rollout": ["canary", "ab"]}),
                 F("online_metric", "Online success metric", "select", "task_success", "", [
                     ("task_success", "Task success rate"), ("thumbs_up", "Thumbs-up rate"), ("edit_distance", "User edit distance"),
                     ("escalation", "Escalation / handoff rate"), ("conversion", "Conversion"), ("retention", "Retention")], show={"rollout": ["canary", "ab", "shadow"]}),
                 F("online_guardrails", "Guardrail metrics", "multiselect", ["latency", "error_rate", "safety_flags"], "Abort the rollout if any degrades.", [
                     ("latency", "Latency"), ("error_rate", "Error rate"), ("safety_flags", "Safety flags"), ("cost", "Cost"), ("refusals", "Refusal rate")], show={"rollout": ["canary", "ab", "shadow"]}),
                 F("sequential_testing", "Sequential testing (always-valid p-values)", "toggle", True, "Lets you peek and stop early without inflating false positives.", show={"rollout": ["ab", "canary"]}),
                 F("online_min_days", "Minimum duration (days)", "int", 7, "Covers weekly seasonality.", show={"rollout": ["ab", "canary"]}, adv=True),
             ]),
             S("Monitoring & retraining", [
                 F("monitors", "Monitor", "multiselect", ["latency", "feedback", "input_drift"], "", [
                     ("latency", "Latency / throughput"), ("cost", "Cost / tokens"), ("input_drift", "Input drift (embeddings)"),
                     ("output_drift", "Output drift"), ("groundedness", "Hallucination / groundedness"), ("toxicity", "Toxicity rate"), ("feedback", "User feedback")]),
                 F("retrain_trigger", "Retraining trigger", "select", "manual", "", [("manual", "Manual"), ("schedule", "Schedule"), ("drift", "Drift threshold"), ("feedback", "Feedback volume")]),
                 F("retrain_schedule", "Cron", "text", "0 3 * * 1", show={"retrain_trigger": ["schedule"]}),
                 F("drift_threshold", "Drift threshold (PSI)", "number", 0.2, show={"retrain_trigger": ["drift"]}),
                 F("feedback_threshold", "New labelled examples", "int", 5000, show={"retrain_trigger": ["feedback"]}),
             ]),
         ]),
]


PRESETS = [
    dict(id="qlora_24gb", name="QLoRA · single 24 GB GPU", desc="8B model, SFT, 4-bit NF4 on an L4 / 4090.",
         patch=dict(base_model="meta-llama/Llama-3.1-8B", method="qlora", objective="sft", gpu_type="L4", num_gpus=1,
                    lora_r=16, lora_alpha=32, learning_rate=2e-4, per_device_batch=2, grad_accum=8,
                    optimizer="paged_adamw_8bit", grad_checkpointing="full", max_seq_len=2048, dist_strategy="single")),
    dict(id="lora_sft", name="LoRA SFT · 1× A100/H100", desc="The strong default for instruction tuning.",
         patch=dict(method="lora", objective="sft", gpu_type="H100-80GB", num_gpus=1, lora_r=32, lora_alpha=64,
                    learning_rate=2e-4, per_device_batch=8, grad_accum=2, optimizer="adamw_torch_fused", dist_strategy="single")),
    dict(id="full_fsdp", name="Full FT · 8× H100 FSDP", desc="Maximum quality on large, clean data.",
         patch=dict(method="full", objective="sft", gpu_type="H100-80GB", num_gpus=8, dist_strategy="fsdp",
                    learning_rate=1e-5, per_device_batch=4, grad_accum=2, weight_decay=0.1, warmup_ratio=0.03, packing="varlen")),
    dict(id="dpo_align", name="DPO alignment", desc="Preference pairs on top of an SFT checkpoint.",
         patch=dict(data_kind="preference", record_schema="preference", objective="dpo", method="lora", pref_beta=0.1,
                    learning_rate=5e-6, epochs=1, lr_scheduler="cosine", warmup_ratio=0.1, packing="none")),
    dict(id="grpo_reasoning", name="GRPO reasoning", desc="Online RL with verifiable rewards (math / code).",
         patch=dict(task_type="reasoning", data_kind="verifiable", record_schema="prompt_only", objective="grpo", method="lora",
                    num_generations=8, max_completion_len=2048, learning_rate=1e-5, kl_coef=0.0, use_vllm_gen=True,
                    reward_sources=["accuracy", "format"], epochs=1, packing="none")),
]


def defaults() -> dict:
    return {f["key"]: f["default"] for st in STAGES for s in st["sections"] for f in s["fields"]}


def fields_by_key() -> dict:
    return {f["key"]: f for st in STAGES for s in st["sections"] for f in s["fields"]}


def public_schema() -> dict:
    return dict(stages=STAGES, presets=PRESETS, defaults=defaults())
