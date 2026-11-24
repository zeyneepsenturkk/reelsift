from django.test import TestCase

from apps.core.exceptions import ServiceError
from apps.curation.models import Collection
from apps.curation.services.approval import approve_collection
from apps.curation.tests.base import make_chat, make_collection, make_story_film, make_user


class ApproveCollectionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.other = make_user("other")
        self.chat = make_chat(self.owner)
        self.film = make_story_film(1)

    def test_owner_approves_with_token_and_timestamp(self):
        collection = make_collection(self.owner, self.chat, films=[self.film])

        approved = approve_collection(collection, self.owner)

        self.assertEqual(approved.status, Collection.Status.APPROVED)
        self.assertTrue(approved.share_token)
        self.assertIsNotNone(approved.approved_at)

    def test_non_owner_is_rejected_and_state_unchanged(self):
        collection = make_collection(self.owner, self.chat, films=[self.film])

        with self.assertRaises(ServiceError) as ctx:
            approve_collection(collection, self.other)

        self.assertEqual(ctx.exception.status_code, 404)
        collection.refresh_from_db()
        self.assertEqual(collection.status, Collection.Status.DRAFT)
        self.assertIsNone(collection.share_token)

    def test_already_approved_is_rejected(self):
        collection = make_collection(self.owner, self.chat, films=[self.film], status="approved")

        with self.assertRaises(ServiceError) as ctx:
            approve_collection(collection, self.owner)

        self.assertEqual(ctx.exception.code, "already_approved")

    def test_empty_collection_is_rejected(self):
        collection = make_collection(self.owner, self.chat)

        with self.assertRaises(ServiceError) as ctx:
            approve_collection(collection, self.owner)

        self.assertEqual(ctx.exception.code, "empty_collection")
