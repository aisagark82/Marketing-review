"""Integration tests: generate real projects and run them against the installed TRL / PEFT / Transformers
on a tiny local Llama model (CPU, ~2 minutes). Skipped when those libraries are not installed.

    pip install torch transformers peft trl datasets accelerate
    python -m unittest tests.integration.test_real_trl -v
"""
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HAVE = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "peft", "trl", "datasets"))


def build_tiny(dst):
    """Tiny ChatML Llama + calculator SFT / preference data; briefly 'pretrained' so it behaves like a base model."""
    import torch
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast
    random.seed(0)
    names = "one two three four five six seven eight nine ten".split()
    sft, pref = [], []
    for _ in range(300):
        a, b = random.randint(1, 5), random.randint(1, 5)
        q, r = f"what is {names[a - 1]} plus {names[b - 1]}", f"the answer is {names[a + b - 1]}"
        wrong = random.choice([x for x in range(1, 11) if x != a + b])
        sft.append({"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": r}]})
        pref.append({"prompt": [{"role": "user", "content": q}], "chosen": [{"role": "assistant", "content": r}],
                     "rejected": [{"role": "assistant", "content": f"the answer is {names[wrong - 1]}"}]})
    (dst / "train.jsonl").write_text("\n".join(json.dumps(r) for r in sft))
    (dst / "pref.jsonl").write_text("\n".join(json.dumps(r) for r in pref))
    tk = Tokenizer(models.BPE())
    tk.pre_tokenizer, tk.decoder = pre_tokenizers.ByteLevel(add_prefix_space=False), decoders.ByteLevel()
    tk.train_from_iterator([m["content"] for r in sft for m in r["messages"]] + ["user assistant system\n"],
                           trainers.BpeTrainer(vocab_size=400, special_tokens=["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<pad>"],
                                               initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tpl = ("{% for m in messages %}{% if m['role'] == 'assistant' %}<|im_start|>assistant\n{% generation %}{{ m['content'] }}<|im_end|>{% endgeneration %}\n"
           "{% else %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endif %}{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, eos_token="<|im_end|>", pad_token="<pad>", chat_template=tpl)
    tok.save_pretrained(dst / "tiny-base")
    torch.manual_seed(0)
    m = LlamaForCausalLM(LlamaConfig(vocab_size=len(tok), hidden_size=64, intermediate_size=176, num_hidden_layers=2, num_attention_heads=4,
                                     num_key_value_heads=2, max_position_embeddings=256, eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id))
    texts = [tok.apply_chat_template(r["messages"], tokenize=False) for r in sft]
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
    for step in range(200):
        b = tok([texts[(step * 16 + i) % len(texts)] for i in range(16)], return_tensors="pt", padding=True)
        loss = m(**b, labels=b.input_ids.masked_fill(b.attention_mask == 0, -100)).loss
        loss.backward()
        opt.step()
        opt.zero_grad()
    m.save_pretrained(dst / "tiny-base")


def project(dst, work, **kw):
    from engine.codegen import generate
    from engine.schema import defaults
    c = dict(defaults(), project_name="tiny", base_model="custom", custom_model_id="tiny-base", custom_params_b=0.00014, custom_hidden=64,
             custom_layers=2, custom_inter=176, custom_kv_dim=32, custom_vocab=388, custom_ctx=256, method="lora", objective="sft",
             precision="fp32", attn_impl="sdpa", use_liger=False, optimizer="adamw_torch", grad_checkpointing="off", tracker="none",
             data_path="train.jsonl", num_examples=300, max_seq_len=128, per_device_batch=8, grad_accum=1, epochs=2, eval_steps=20, save_steps=20,
             save_total_limit=10, learning_rate=3e-3, dedup="none", pii_scrub="none", min_tokens=0, record_env=False, tf32=False,
             dataloader_workers=0, num_proc=1, lora_r=8, lora_alpha=16, gpu_type="T4", logging_steps=5, overfit_steps=40, lr_range_bounds="1e-5,1")
    c.update(kw)
    dst.mkdir(parents=True, exist_ok=True)
    for name, text in generate(c).items():
        (dst / name).parent.mkdir(parents=True, exist_ok=True)
        (dst / name).write_text(text)
    for f in ("train.jsonl", "pref.jsonl"):
        shutil.copy(work / f, dst / f)
    (dst / "tiny-base").symlink_to(work / "tiny-base")


def run(cmd, cwd, env=None):
    p = subprocess.run([sys.executable] + cmd, cwd=cwd, env=dict(os.environ, **(env or {})), capture_output=True, text=True, timeout=1800)
    return p.returncode, p.stdout + p.stderr


@unittest.skipUnless(HAVE, "needs torch, transformers, peft, trl, datasets")
class RealTRL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        build_tiny(cls.tmp)
        shim = cls.tmp / "shim" / "vllm"
        (shim / "lora").mkdir(parents=True)
        shutil.copy(ROOT / "tests/integration/hf_vllm_init.py", shim / "__init__.py")
        (shim / "lora" / "__init__.py").write_text("")
        shutil.copy(ROOT / "tests/integration/hf_vllm_lora_request.py", shim / "lora" / "request.py")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_sft_checks_train_monitor_diagnostics(self):
        d = self.tmp / "sft"
        project(d, self.tmp, preflight_checks=["template_render", "loss_mask", "truncation", "trainable_audit", "identity_init", "initial_loss", "overfit_batch", "lr_range"],
                monitors_train=["nan_guard", "loss_spike", "gen_gap", "sample_gens"], ft_diagnostics=["stop_behavior", "length_drift", "diversity"],
                objective_tests=["sft_heldout_ppl"], technique_tests=["adapter_norms"], ckpt_selection="best_val_loss", task_metrics=["exact_match"])
        rc, out = run(["ft_checks.py"], d)
        self.assertEqual(rc, 0, out[-3000:])
        rc, out = run(["train.py"], d)
        self.assertEqual(rc, 0, out[-3000:])
        self.assertTrue((d / "outputs/tiny/final/adapter_model.safetensors").exists())
        self.assertTrue((d / "outputs/tiny/sample_generations.jsonl").exists())
        rc, out = run(["ft_diagnostics.py", "--limit", "16"], d, {"PYTHONPATH": str(self.tmp / "shim")})
        self.assertIn("sft_heldout_ppl", out)
        self.assertNotIn("Traceback", out, out[-3000:])

    def test_dpo_step0_loss_is_ln2(self):
        d = self.tmp / "dpo"
        project(d, self.tmp, objective="dpo", data_kind="preference", record_schema="preference", data_path="pref.jsonl", ref_model="peft_disabled",
                train_on_completions=False, preflight_checks=["template_render", "identity_init", "initial_loss"], monitors_train=[])
        rc, out = run(["ft_checks.py"], d)
        self.assertEqual(rc, 0, out[-3000:])
        self.assertIn("expected ln2", out)

    def test_broken_template_is_caught(self):
        d = self.tmp / "broken"
        project(d, self.tmp, preflight_checks=["template_render"], monitors_train=[])
        (d / "tiny-base").unlink()
        shutil.copytree(self.tmp / "tiny-base", d / "tiny-base")
        f = d / "tiny-base" / "chat_template.jinja"
        if f.exists():
            f.write_text(f.read_text().replace("{% generation %}", "").replace("{% endgeneration %}", "").replace("<|im_end|>", ""))
        else:
            cfgp = d / "tiny-base" / "tokenizer_config.json"
            c = json.loads(cfgp.read_text())
            c["chat_template"] = c["chat_template"].replace("{% generation %}", "").replace("{% endgeneration %}", "").replace("<|im_end|>", "")
            cfgp.write_text(json.dumps(c))
        rc, out = run(["ft_checks.py"], d)
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL] template_render", out)


if __name__ == "__main__":
    unittest.main()
