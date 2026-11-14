"""Append-only fingerprints for the independent chain interpretation prompt."""

from types import MappingProxyType

CHAIN_PROMPT_HISTORY = MappingProxyType(
    {
        "chain-risk-interpret-v1": (
            "709c65d2a2dd789d5cd3ddc41acf931ac786eb33dcf85f98a8efb145f5787dc5"
        ),
    }
)
CHAIN_PROMPT_VERSION = "chain-risk-interpret-v1"
CHAIN_PROMPT_SHA256 = CHAIN_PROMPT_HISTORY[CHAIN_PROMPT_VERSION]
