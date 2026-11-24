from ninja import Router

from apps.agent.api_schemas import LLMSettingsIn, LLMSettingsOut, LLMTestOut
from apps.agent.services import llm_config, llm_probe
from apps.core.auth import session_auth

router = Router(tags=["settings"], auth=session_auth)


@router.get("/settings/llm", response=LLMSettingsOut)
def get_llm_settings(request):
    return llm_config.serialize(llm_config.get_effective())


@router.put("/settings/llm", response=LLMSettingsOut)
def put_llm_settings(request, payload: LLMSettingsIn):
    config = llm_config.save_settings(request.user, **payload.dict())
    return llm_config.serialize(config)


@router.post("/settings/llm/test", response=LLMTestOut, exclude_none=True)
def check_llm_connection(request):
    return llm_probe.probe()
