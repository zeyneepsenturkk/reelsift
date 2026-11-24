from ninja import Router

from apps.core.auth import session_auth
from apps.core.throttles import ShareThrottle
from apps.curation.schemas import (
    CollectionOut,
    CollectionPatchIn,
    CollectionSummaryOut,
    SharedCollectionOut,
)
from apps.curation.services import collections
from apps.curation.services.approval import approve_collection
from apps.curation.services.publishing import publish_collection
from apps.curation.services.serializers import (
    approved_collections,
    get_owned_collection,
    get_shared_collection,
    serialize_collection,
    serialize_shared,
    serialize_summary,
)

router = Router(tags=["collections"], auth=session_auth)


@router.get("/collections", response=list[CollectionSummaryOut])
def list_collections(request):
    return [serialize_summary(collection) for collection in approved_collections(request.user)]


@router.get("/collections/{collection_id}", response=CollectionOut)
def get_collection(request, collection_id: int):
    return serialize_collection(get_owned_collection(collection_id, request.user))


@router.patch("/collections/{collection_id}", response=CollectionOut)
def patch_collection(request, collection_id: int, payload: CollectionPatchIn):
    owned = get_owned_collection(collection_id, request.user)
    updated = collections.update_collection(
        owned.pk, title=payload.title, description=payload.description
    )
    return serialize_collection(updated)


@router.delete("/collections/{collection_id}/films/{film_id}", response=CollectionOut)
def delete_collection_film(request, collection_id: int, film_id: int):
    owned = get_owned_collection(collection_id, request.user)
    return serialize_collection(collections.remove_film(owned.pk, film_id))


@router.post("/collections/{collection_id}/approve", response=CollectionOut)
def approve(request, collection_id: int):
    owned = get_owned_collection(collection_id, request.user)
    approve_collection(owned, request.user)
    return serialize_collection(get_owned_collection(collection_id, request.user))


@router.post("/collections/{collection_id}/publish", response=CollectionOut)
def publish(request, collection_id: int):
    owned = get_owned_collection(collection_id, request.user)
    publish_collection(owned, request.user)
    return serialize_collection(get_owned_collection(collection_id, request.user))


# Girişsiz uç: kaba kuvvetle anahtar taramayı yavaşlatmak için IP başına dakikada 60 istek.
@router.get(
    "/share/{token}",
    response=SharedCollectionOut,
    auth=None,
    throttle=[ShareThrottle("60/m")],
)
def get_shared(request, token: str):
    return serialize_shared(get_shared_collection(token))
