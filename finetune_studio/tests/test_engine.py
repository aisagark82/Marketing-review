"""Engine tests. Run from finetune_studio/:  python -m pytest tests  (or python -m unittest discover tests)"""

import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.codegen import generate  # noqa: E402
from engine.dataset import profile  # noqa: E402
from engine.estimator import estimate, memory_breakdown  # noqa: E402
from engine.recommender import recommend  # noqa: E402
from engine.schema import STAGES, defaults, fields_by_key  # noqa: E402
from engine.validator import validate  # noqa: E402

OBJECTIVES = ["sft", "cpt", "dpo", "orpo", "simpo", "kto", "cpo", "grpo", "rloo", "ppo", "reward_model", "distill", "classifier"]
METHODS = ["full", "freeze", "lora", "qlora", "dora", "adalora", "vera", "ia3", "prefix", "prompt_tuning", "bitfit", "galore"]


def cfg(**kw):
    return dict(defaults(), **kw)


class SchemaTests(unittest.TestCase):
    def test_keys_unique_and_show_refs_exist(self):
        keys = [f["key"] for st in STAGES for s in st["sections"] for f in s["fields"]]
        self.assertEqual(len(keys), len(set(keys)))
        known = set(keys)
        for st in STAGES:
            for s in st["sections"]:
                for cond in [s.get("show") or {}] + [f.get("show") or {} for f in s["fields"]]:
                    self.assertTrue(set(cond) <= known, cond)

    def test_select_defaults_are_options(self):
        for f in fields_by_key().values():
            if f["type"] == "select":
                self.assertIn(f["default"], [o["value"] for o in f["options"]], f["key"])


class EstimatorTests(unittest.TestCase):
    def test_peft_uses_far_less_memory_than_full(self):
        full = memory_breakdown(cfg(method="full"))["total_gb"]
        lora = memory_breakdown(cfg(method="lora"))["total_gb"]
        qlora = memory_breakdown(cfg(method="qlora"))["total_gb"]
        self.assertGreater(full, 4 * lora)
        self.assertLess(qlora, lora)

    def test_full_8b_needs_about_16_bytes_per_param(self):
        m = memory_breakdown(cfg(method="full", dist_strategy="single"))
        static = m["parts"]["weights"] + m["parts"]["grads"] + m["parts"]["optimizer"]
        self.assertAlmostEqual(static / 8.03, 16 / 1.074, delta=1.0)  # GiB per B params

    def test_sharding_reduces_per_gpu_memory(self):
        base = cfg(method="full", num_gpus=8)
        self.assertLess(memory_breakdown(base, "zero3")["total_gb"], memory_breakdown(base, "zero2")["total_gb"])
        self.assertLess(memory_breakdown(base, "zero2")["total_gb"], memory_breakdown(base, "ddp")["total_gb"])

    def test_auto_strategy_picks_one_that_fits(self):
        e = estimate(cfg(method="full", num_gpus=8, gpu_type="H100-80GB"))
        self.assertTrue(e["memory"]["fits"])
        self.assertIn(e["strategy"], ("zero2", "fsdp"))

    def test_lora_trainable_params_llama8b_r16(self):
        # all-linear r=16 on Llama-3.1-8B is ~42M trainable params
        e = estimate(cfg(method="lora", lora_r=16))
        self.assertAlmostEqual(e["trainable_params"] / 1e6, 41.9, delta=0.5)


class RecommenderTests(unittest.TestCase):
    def test_objective_follows_data_shape(self):
        expect = {"sft": "sft", "preference": "dpo", "binary_feedback": "kto", "verifiable": "grpo", "raw_text": "cpt", "labels": "classifier"}
        for kind, obj in expect.items():
            self.assertEqual(recommend(cfg(data_kind=kind))["objective"]["id"], obj, kind)

    def test_preference_on_base_model_suggests_orpo(self):
        self.assertEqual(recommend(cfg(data_kind="preference", model_variant="base"))["objective"]["id"], "orpo")

    def test_small_gpu_prefers_qlora_and_never_recommends_oom(self):
        r = recommend(cfg(gpu_type="T4", base_model="meta-llama/Llama-3.1-8B"))
        self.assertTrue(r["techniques"][0]["fits"])
        self.assertEqual(r["patch"]["method"], "qlora")
        self.assertEqual(r["patch"]["precision"], "fp16")

    def test_large_data_big_shift_quality_on_big_cluster_prefers_full(self):
        r = recommend(cfg(num_examples=2_000_000, domain_shift="high", priority="quality", preserve_general=False,
                          gpu_type="H100-80GB", num_gpus=8))
        self.assertEqual(r["patch"]["method"], "full")
        self.assertLessEqual(r["patch"]["learning_rate"], 2e-5)

    def test_multi_tenant_keeps_adapters(self):
        r = recommend(cfg(deploy_target="multi_tenant"))
        self.assertIn(r["patch"]["method"], ("lora", "qlora", "dora", "ia3"))
        self.assertFalse(r["patch"]["merge_adapters"])

    def test_recommended_config_passes_preflight(self):
        for kind in ("sft", "preference", "binary_feedback", "verifiable", "raw_text", "labels"):
            c = cfg(data_kind=kind)
            c.update(recommend(c)["patch"])
            errors = [i for i in validate(c) if i["level"] == "error"]
            self.assertEqual(errors, [], kind)

    def test_grpo_batch_divisible_by_group(self):
        r = recommend(cfg(data_kind="verifiable", num_gpus=3))
        p = r["patch"]
        self.assertEqual((p["per_device_batch"] * 3 * p["grad_accum"]) % p["num_generations"], 0)


class ValidatorTests(unittest.TestCase):
    def codes(self, **kw):
        return {i["key"] for i in validate(cfg(**kw)) if i["level"] == "error"}

    def test_catches_common_mistakes(self):
        self.assertIn("record_schema", self.codes(objective="dpo"))
        self.assertIn("packing", self.codes(objective="dpo", record_schema="preference", packing="varlen"))
        self.assertIn("precision", self.codes(gpu_type="T4", method="qlora"))
        self.assertIn("learning_rate", self.codes(method="full", num_gpus=8, learning_rate=2e-4))
        self.assertIn("gpu_type", self.codes(method="full"))
        self.assertIn("ref_model", self.codes(objective="dpo", record_schema="preference", method="full", num_gpus=8, ref_model="peft_disabled"))

    def test_defaults_are_clean(self):
        self.assertEqual([i for i in validate(cfg()) if i["level"] == "error"], [])


class CodegenTests(unittest.TestCase):
    def test_every_objective_and_method_generates_valid_code(self):
        for o in OBJECTIVES:
            for m in METHODS:
                for extra in ({}, dict(num_gpus=8, dist_strategy="zero3", packing="varlen", loraplus_ratio=16, platform="slurm",
                                       split_strategy="group", dedup="exact", min_tokens=4, pii_scrub="regex", early_stopping_patience=2,
                                       record_schema="alpaca", system_prompt="Be concise.", ptq_method="awq")):
                    files = generate(cfg(objective=o, method=m, **extra))
                    for name, text in files.items():
                        if name.endswith(".py"):
                            ast.parse(text, f"{o}/{m}/{name}")
                        if name.endswith(".json"):
                            json.loads(text)

    def test_zero_strategy_emits_deepspeed_config(self):
        files = generate(cfg(method="full", num_gpus=8, dist_strategy="zero3"))
        self.assertEqual(json.loads(files["ds_config.json"])["zero_optimization"]["stage"], 3)
        self.assertIn("deepspeed='ds_config.json'", files["train.py"])

    def test_qlora_script_has_bnb(self):
        t = generate(cfg(method="qlora"))["train.py"]
        self.assertIn("BitsAndBytesConfig(load_in_4bit=True", t)
        self.assertIn("prepare_model_for_kbit_training", t)


class DatasetTests(unittest.TestCase):
    def test_detects_preference_schema_and_dupes(self):
        rows = [{"prompt": "q", "chosen": "a", "rejected": "b"}] * 3 + [{"prompt": "x y", "chosen": "c", "rejected": "d"}]
        p = profile("d.jsonl", "\n".join(json.dumps(r) for r in rows))
        self.assertEqual(p["schema"], "preference")
        self.assertEqual(p["data_kind"], "preference")
        self.assertEqual(p["duplicates"], 2)

    def test_csv_labels_and_pii(self):
        text = "text,label\nhello me@x.com,a\nfoo,a\nbar,b\n"
        p = profile("d.csv", text)
        self.assertEqual(p["schema"], "text_label")
        self.assertEqual(p["labels"], {"a": 2, "b": 1})
        self.assertTrue(any("PII" in f["msg"] for f in p["flags"]))


if __name__ == "__main__":
    unittest.main()
