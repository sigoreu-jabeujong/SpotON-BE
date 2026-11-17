"""Append-only fingerprints for the v2 analysis interpretation prompt."""

from types import MappingProxyType

V2_PROMPT_HISTORY = MappingProxyType(
    {
        "chain-risk-interpret-v1": (
            "709c65d2a2dd789d5cd3ddc41acf931ac786eb33dcf85f98a8efb145f5787dc5"
        ),
        "chain-risk-interpret-v2": (
            "6eb303b09965f7476ce67da3f0430d4af60b1f6a82804b9aea2295eee6d11b3b"
        ),
        "analysis-risk-interpret-v3": (
            "ea228f546ad919df580690efb9f15a7ee1836f06a0acd6cb8ee810b39d122303"
        ),
    }
)
V2_PROMPT_VERSION = "analysis-risk-interpret-v3"
V2_PROMPT_SHA256 = V2_PROMPT_HISTORY[V2_PROMPT_VERSION]
