"""
LLM Router
Reports which AI provider is serving requests and whether the chain is healthy.
"""

from fastapi import APIRouter

from services import llm

router = APIRouter()


@router.get("/api/llm/status")
async def llm_status(include_models: bool = False):
    """
    Current LLM provider configuration and health.

    Returns the active provider/model, the configured fallback chain, and which
    entries were skipped (missing API key, unknown provider name, or no model).
    Pass `?include_models=true` to also list the model ids each provider offers —
    useful when a configured model id has gone stale.

    API keys are never included in the response.
    """
    return await llm.active_provider_info(include_models=include_models)
