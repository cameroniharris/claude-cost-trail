"""Turn a single API response's `usage` block into dollars.

Prices live in pricing.json so a price change is a data edit, not a code change.
Everything is an estimate at API list prices: subscription (Pro/Max) users are
not billed per token, so for them the number means "what this would have cost
on the API".
"""

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATE_SUFFIX = re.compile(r"-\d{8}$")


class Pricing:
    def __init__(self, path=None):
        with open(path or os.path.join(_HERE, "pricing.json")) as f:
            data = json.load(f)
        self.as_of = data.get("as_of", "")
        self.models = data["models"]
        self.write_5m = data.get("cache_write_5m_multiplier", 1.25)
        self.write_1h = data.get("cache_write_1h_multiplier", 2.0)
        self.web_search = data.get("web_search_per_request", 0.0)
        self.fallback = data.get("fallback_model")
        self.unknown_models = set()
        self._cache = {}

    def rates_for(self, model):
        """Longest-prefix match on the model ID; falls back (and remembers) when unknown."""
        if model in self._cache:
            return self._cache[model]
        base = _DATE_SUFFIX.sub("", model or "")
        base = base[base.find("claude"):] if "claude" in base else base  # drop "us.anthropic." etc.
        best = None
        for key in self.models:
            if base == key or base.startswith(key + "-") or base.startswith(key + "@"):
                if best is None or len(key) > len(best):
                    best = key
        if best is None:
            self.unknown_models.add(model)
            best = self.fallback
        self._cache[model] = self.models[best]
        return self._cache[model]

    def cost(self, model, usage):
        """Dollar cost of one API response. `usage` is the raw usage dict from the log."""
        if not usage or model == "<synthetic>":
            return 0.0
        r = self.rates_for(model)
        per = 1_000_000.0
        cache_creation = usage.get("cache_creation") or {}
        w1h = cache_creation.get("ephemeral_1h_input_tokens")
        w5m = cache_creation.get("ephemeral_5m_input_tokens")
        if w1h is None and w5m is None:
            # Older logs only report the total; treat it all as the 5-minute TTL.
            w5m, w1h = usage.get("cache_creation_input_tokens") or 0, 0
        dollars = (
            (usage.get("input_tokens") or 0) * r["input"]
            + (usage.get("output_tokens") or 0) * r["output"]
            + (usage.get("cache_read_input_tokens") or 0) * r["cache_read"]
            + (w5m or 0) * r["input"] * self.write_5m
            + (w1h or 0) * r["input"] * self.write_1h
        ) / per
        if usage.get("speed") == "fast":
            dollars *= r.get("fast_multiplier", 1.0)
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
        return dollars + searches * self.web_search


def model_label(model):
    """"claude-opus-5-5-20260101" -> "Opus 5.5"; "claude-3-5-haiku" -> "Haiku 3.5"."""
    if not model or model == "<synthetic>":
        return "Other"
    base = _DATE_SUFFIX.sub("", model).split("@")[0]
    base = base[base.find("claude") + len("claude-"):] if "claude" in base else base
    parts = [x for x in base.split("-") if x]
    words = [x for x in parts if not x.isdigit()]
    digits = [x for x in parts if x.isdigit()]
    if not words:
        return model
    return " ".join([words[0].title()] + ([".".join(digits)] if digits else []))


def model_matches(model, wanted):
    """Does a model ID match a --claude-model filter like "fable", "opus 5.5" or "claude-sonnet-5-5"?"""
    if not wanted:
        return True
    w = wanted.lower().strip()
    return w in (model or "").lower() or w in model_label(model).lower()
