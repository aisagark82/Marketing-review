"""Minimal vLLM stand-in backed by transformers.generate — for testing ft_diagnostics / eval_suite off-GPU."""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

class SamplingParams:
    def __init__(self, n=1, temperature=0.0, top_p=1.0, max_tokens=64, seed=0, **kw):
        self.n, self.temperature, self.top_p, self.max_tokens, self.seed = n, temperature, top_p, min(max_tokens, 48), seed

class _C:
    def __init__(self, text, fin): self.text, self.finish_reason = text, fin
class _O:
    def __init__(self, outs): self.outputs = outs

class LLM:
    def __init__(self, model, enable_lora=False, **kw):
        print(f"[hf-vllm] load {model} lora={enable_lora}")
        self.tok = AutoTokenizer.from_pretrained(model)
        self.base = AutoModelForCausalLM.from_pretrained(model).eval()
        self.adapters = {}
    def _model(self, req):
        if req is None: return self.base
        if req.path not in self.adapters:
            from peft import PeftModel
            fresh = AutoModelForCausalLM.from_pretrained(self.base.name_or_path).eval()
            self.adapters[req.path] = PeftModel.from_pretrained(fresh, req.path).eval()
        return self.adapters[req.path]
    def chat(self, convs, sp, use_tqdm=False, lora_request=None, **kw):
        m = self._model(lora_request); torch.manual_seed(sp.seed); outs = []
        for c in convs:
            text = self.tok.apply_chat_template(c, tokenize=False, add_generation_prompt=True)
            ids = self.tok(text, return_tensors="pt", add_special_tokens=False).input_ids
            res = []
            for _ in range(sp.n):
                with torch.no_grad():
                    g = m.generate(input_ids=ids, max_new_tokens=sp.max_tokens, do_sample=sp.temperature > 0,
                                   temperature=sp.temperature if sp.temperature > 0 else None, top_p=sp.top_p if sp.temperature > 0 else None,
                                   pad_token_id=self.tok.pad_token_id, eos_token_id=self.tok.eos_token_id)
                new = g[0, ids.shape[1]:]
                stopped = bool((new == self.tok.eos_token_id).any())
                res.append(_C(self.tok.decode(new, skip_special_tokens=True), "stop" if stopped else "length"))
            outs.append(_O(res))
        return outs
