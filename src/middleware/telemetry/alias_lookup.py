#!/usr/bin/env python3
from __future__ import annotations

from typing import Dict, List

from ...config.models import ModelSpec


def create_alias_lookup(model_specs: List[ModelSpec]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for spec in model_specs:
        if getattr(spec, "alias", None):
            upstream = spec.upstream_model
            provider = getattr(spec, "provider", "openai")
            prefix = f"{provider}/"
            if not upstream.startswith(prefix):
                upstream = f"{prefix}{upstream}"
            lookup[spec.alias] = upstream
    return lookup
