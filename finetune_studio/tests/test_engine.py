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
from engine.testing import detectable_effect, required_n, summary, winrate_n  # noqa: E402
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


class TestingMethodologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = generate(cfg(project_name="t"))["eval_suite.py"]
        cls.suite = {}
        exec(compile(src, "eval_suite.py", "exec"), cls.suite)  # stdlib-only at import time

    def test_power_analysis(self):
        n = required_n(0.03, 0.7)
        self.assertTrue(3000 < n < 4200, n)          # textbook two-proportion result ≈ 3.6k
        self.assertAlmostEqual(detectable_effect(n, 0.7), 0.03, delta=0.002)
        self.assertLess(required_n(0.05, 0.7), required_n(0.02, 0.7))
        self.assertTrue(700 < winrate_n(0.05) < 900, winrate_n(0.05))

    def test_summary_flags_underpowered_test_set(self):
        self.assertFalse(summary(cfg(num_examples=2000, test_ratio=0.05))["adequate"])
        self.assertTrue(summary(cfg(num_examples=100000, test_ratio=0.05))["adequate"])

    def test_recommended_plan_is_task_aware(self):
        rag = recommend(cfg(task_type="rag", data_privacy="regulated"))["patch"]
        self.assertIn("faithfulness", rag["grounding_methods"])
        self.assertIn("prompt_injection", rag["safety_suites"])
        self.assertIn("pii_leak", rag["safety_suites"])
        self.assertEqual(recommend(cfg(task_type="classification"))["patch"]["sig_test"], "mcnemar")
        self.assertIn("prompted_baseline", rag["compare_against"])

    def test_suite_statistics(self):
        S = self.suite
        self.assertAlmostEqual(S["mcnemar"]([1] * 10 + [0] * 10, [0] * 10 + [0] * 10), 2 / 2 ** 10, places=6)
        self.assertEqual(S["mcnemar"]([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(S["cohen_kappa"](list("AABB"), list("AABB")), 1.0)
        from collections import Counter
        self.assertAlmostEqual(S["fleiss_kappa"]([Counter(A=3), Counter(B=3)]), 1.0)
        adj = S["adjust"]({"x": 0.01, "y": 0.04})       # Holm: 0.02, 0.04
        self.assertAlmostEqual(adj["x"], 0.02)
        self.assertAlmostEqual(adj["y"], 0.04)
        diff, ci, p = S["paired_bootstrap"]([1.0] * 50, [0.0] * 50)
        self.assertEqual(diff, 1.0)
        self.assertLess(p, 0.01)
        self.assertLess(S["wilcoxon"]([1.0] * 30, [0.0] * 30), 0.001)

    def test_suite_assertions_and_perturbations(self):
        S = self.suite
        check = S["check"]
        self.assertTrue(check({"type": "numeric", "value": 391, "tol": 0}, "The answer is 391."))
        self.assertTrue(check({"type": "json_schema", "value": {"type": "object", "required": ["a"]}}, 'Sure: {"a": 1}'))
        self.assertFalse(check({"type": "json_schema", "value": {"type": "object", "required": ["a"]}}, "no json"))
        self.assertTrue(check({"type": "tool_call", "value": {"name": "f", "arguments": {"city": "Paris"}}},
                              '{"name": "f", "arguments": {"city": "paris"}}'))
        self.assertTrue(check({"type": "not_contains", "value": "x"}, "abc"))
        import random
        a = S["perturb"]("hello wonderful world", "typos", random.Random("perturb-typos"))
        b = S["perturb"]("hello wonderful world", "typos", random.Random("perturb-typos"))
        self.assertEqual(a, b)
        self.assertAlmostEqual(S["rouge_l"]("a b c", "a b c"), 1.0)

    def test_generated_testing_files(self):
        files = generate(cfg(test_sets=["in_dist", "golden"], safety_suites=["custom_safety"], red_team_tool="garak", load_test=True))
        for f in ("eval_suite.py", "TEST_PLAN.md", "gates.json", "tests/golden.example.jsonl", "tests/safety.example.jsonl", "loadtest.sh", "redteam.sh"):
            self.assertIn(f, files)
        for line in files["tests/golden.example.jsonl"].splitlines():
            json.loads(line)
        self.assertIn("python eval_suite.py", files["eval.sh"])


class FineTuneTestingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = generate(cfg(project_name="t"))
        cls.mon, cls.diag, cls.sweep = {}, {}, {}
        exec(compile(generate(cfg(monitors_train=["nan_guard"]))["ft_monitor.py"], "ft_monitor.py", "exec"), cls.mon)
        exec(compile(files["ft_diagnostics.py"], "ft_diagnostics.py", "exec"), cls.diag)
        exec(compile(files["sweep.py"], "sweep.py", "exec"), cls.sweep)
        for f in ("ft_checks.py", "ft_diagnostics.py", "sweep.py"):
            ast.parse(files[f])

    def _monitor(self, on, tmp):
        return self.mon["FTMonitor"]({"monitors_train": on, "monitor_action": "stop"}, tmp)

    def test_monitor_alerts(self):
        import tempfile
        from types import SimpleNamespace as NS
        with tempfile.TemporaryDirectory() as tmp:
            m = self._monitor(["nan_guard", "loss_spike", "dpo_displacement", "rl_entropy", "rl_reward_hacking", "gen_gap"], tmp)
            ctl = NS(should_training_stop=False, should_save=False)
            st = lambda step: NS(global_step=step, max_steps=1000)  # noqa: E731
            for i in range(1, 40):
                m.on_log(None, st(i), ctl, {"loss": 1.0, "logps/chosen": -20.0, "entropy": 1.0, "reward": 0.1, "completions/mean_length": 100})
            m.on_log(None, st(41), ctl, {"loss": 9.0})                                  # spike
            m.on_log(None, st(42), ctl, {"logps/chosen": -40.0})                        # likelihood displacement
            m.on_log(None, st(43), ctl, {"reward": 0.9, "completions/mean_length": 400})  # reward hacking
            for e in (1.0, 1.01, 1.02):
                m.on_log(None, st(44), ctl, {"eval_loss": e})                          # overfitting
            kinds = {a["kind"] for a in m.alerts}
            self.assertTrue({"loss_spike", "likelihood_displacement", "reward_hacking_suspect", "overfitting"} <= kinds, kinds)
            self.assertFalse(ctl.should_training_stop)
            m.on_log(None, st(45), ctl, {"entropy": 0.01})                              # entropy collapse is critical
            self.assertTrue(ctl.should_training_stop)
            m.on_log(None, st(46), ctl, {"loss": float("nan")})
            self.assertIn("nan", {a["kind"] for a in m.alerts})

    def test_diagnostic_metrics(self):
        D = self.diag
        self.assertEqual(D["distinct_n"](["a b c", "a b c"], 1), 0.5)
        self.assertGreater(D["self_bleu"](["the cat sat on the mat"] * 3), 0.99)
        self.assertLess(D["self_bleu"](["alpha beta gamma delta", "one two three four", "red green blue black"]), 0.01)
        self.assertAlmostEqual(D["ece"]([1.0, 1.0], [1.0, 1.0]), 0.0)
        self.assertAlmostEqual(D["ece"]([0.9] * 10, [0.0] * 10), 0.9)
        self.assertAlmostEqual(D["pass_at_k"](10, 1, 1), 0.1)
        self.assertEqual(D["pass_at_k"](10, 10, 5), 1.0)
        self.assertAlmostEqual(D["pass_at_k"](4, 2, 2), 1 - 1 / 6)
        lc, n = D["length_matched_winrate"]([(1.0, 100, 50), (0.0, 50, 52), (1.0, 60, 58)])
        self.assertEqual((lc, n), (0.5, 2))

    def test_sweep_math(self):
        W = self.sweep
        ns = [100, 200, 400, 800]
        losses = [3 * n ** -0.4 + 0.5 for n in ns]
        a, b, c = W["fit_power_law"](ns, losses)
        self.assertAlmostEqual(b, 0.4, delta=0.05)
        self.assertAlmostEqual(c, 0.5, delta=0.05)
        sched = W["halving_schedule"](16, 300)
        self.assertEqual(sched[0][0], 16)
        self.assertEqual(sched[-1], (1, 300))
        self.assertTrue(all(x[1] <= y[1] for x, y in zip(sched, sched[1:])))

    def test_recommended_ft_tests_follow_objective_and_method(self):
        dpo = recommend(cfg(data_kind="preference"))["patch"]
        self.assertIn("dpo_displacement", dpo["monitors_train"])
        self.assertIn("pref_accuracy", dpo["objective_tests"])
        grpo = recommend(cfg(data_kind="verifiable"))["patch"]
        self.assertIn("rl_reward_hacking", grpo["monitors_train"])
        self.assertIn("rl_passk", grpo["objective_tests"])
        self.assertNotIn("overfit_batch", grpo["preflight_checks"])
        q = recommend(cfg(gpu_type="T4"))["patch"]
        self.assertIn("qlora_bf16_merge", q["technique_tests"])
        cls = recommend(cfg(data_kind="labels"))["patch"]
        self.assertIn("cls_report", cls["objective_tests"])

    def test_ft_validator(self):
        keys = {i["key"] for i in validate(cfg(objective="dpo", record_schema="preference", monitors_train=["nan_guard"], objective_tests=["rl_passk"]))
                if i["level"] == "warn"}
        self.assertIn("monitors_train", keys)
        self.assertIn("objective_tests", keys)
        errs = {i["key"] for i in validate(cfg(ckpt_selection="soup", soup_k=5, save_total_limit=2)) if i["level"] == "error"}
        self.assertIn("soup_k", errs)

    def test_train_py_supports_sweeps_and_import(self):
        t = generate(cfg(monitors_train=["nan_guard"]))["train.py"]
        for needle in ("FT_OVERRIDES", "FT_DATA_FRACTION", "FT_OUTPUT_DIR", "if __name__ == '__main__':", "FTMonitor", "compat(SFTConfig"):
            self.assertIn(needle, t)
        self.assertIn("mixed_precision: 'no'", generate(cfg(precision="fp32"))["accelerate_config.yaml"])


if __name__ == "__main__":
    unittest.main()
