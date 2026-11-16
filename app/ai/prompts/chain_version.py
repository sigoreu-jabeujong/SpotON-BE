"""Append-only fingerprints for the independent chain interpretation prompt."""

from types import MappingProxyType

CHAIN_PROMPT_HISTORY = MappingProxyType(
    {
        "chain-risk-interpret-v1": (
            "709c65d2a2dd789d5cd3ddc41acf931ac786eb33dcf85f98a8efb145f5787dc5"
        ),
        "chain-risk-interpret-v2": (
            "6eb303b09965f7476ce67da3f0430d4af60b1f6a82804b9aea2295eee6d11b3b"
        ),
    }
)
CHAIN_PROMPT_VERSION = "chain-risk-interpret-v2"
CHAIN_PROMPT_SHA256 = CHAIN_PROMPT_HISTORY[CHAIN_PROMPT_VERSION]
