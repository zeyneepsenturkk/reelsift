from ninja import Router

from apps.chats.schemas import ChatOut, ChatSummaryOut
from apps.chats.services import chats
from apps.core.auth import session_auth

router = Router(tags=["chats"], auth=session_auth)


@router.get("/chats", response=list[ChatSummaryOut])
def list_chats(request):
    return [chats.summarize(chat) for chat in chats.list_chats(request.user)]


@router.post("/chats", response={201: ChatSummaryOut})
def create_chat(request):
    return 201, chats.summarize(chats.create_chat(request.user))


@router.get("/chats/{chat_id}", response=ChatOut)
def get_chat(request, chat_id: int):
    return chats.chat_detail(chats.get_owned_chat(chat_id, request.user))
