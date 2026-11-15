"""Verified standard text Responses contracts, 2026-11-11; USD per million."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    label: str
    effort: str
    input: float
    cached: float
    write: float
    output: float


MODELS={
    'gpt-6-luna':ModelSpec('GPT-6 Luna','none',.10,.01,.125,.50),
    'gpt-6.1-terra':ModelSpec('GPT-6.1 Terra','none',1,.05,1.25,5),
    'gpt-6.1-sol':ModelSpec('GPT-6.1 Sol','low',2,.10,2.50,10),
}
DEFAULT_MODEL='gpt-6-luna'


def model_spec(model):
    try:return MODELS[model]
    except (KeyError,TypeError):raise ValueError('Model sözleşmesi doğrulanmamış. Luna, Terra veya Sol seçin.') from None
