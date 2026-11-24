from django.test import TestCase

from apps.chats.models import DEFAULT_TITLE, Message
from apps.chats.services import chats
from apps.chats.tests.base import make_chat, make_message, make_user


class ReserveMessageIdTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.chat = make_chat(self.user)

    def test_reserved_ids_are_unique_and_usable_for_the_assistant_message(self):
        first = chats.reserve_message_id()
        second = chats.reserve_message_id()
        self.assertGreater(second, first)

        user_message = chats.save_user_message(self.chat, "Merhaba")
        message = chats.save_assistant_message(
            self.chat,
            message_id=second,
            text="Selam",
            steps=[],
            duration_s=1.0,
            collection_id=None,
            suggestions=[],
        )

        self.assertEqual(message.pk, second)
        self.assertGreater(
            user_message.pk, second
        )  # ayrılan kimlik sonradan açılan mesajdan küçüktür
        self.assertEqual(Message.objects.get(pk=second).text, "Selam")


class TitleTests(TestCase):
    def setUp(self):
        self.chat = make_chat(make_user())

    def test_title_comes_from_collection_title_first(self):
        chat = chats.update_title(self.chat, collection_title="Karlı kasabalar", user_text="x")

        self.assertEqual(chat.title, "Karlı kasabalar")

    def test_title_falls_back_to_first_40_characters(self):
        text = "Küçük bir Fransız kasabasında geçen aile komedileri ve fazlası"

        chat = chats.update_title(self.chat, collection_title=None, user_text=text)

        self.assertEqual(chat.title, text[:40].rstrip() + "…")
        self.assertLessEqual(len(chat.title), 41)

    def test_short_text_is_kept_as_is_and_existing_title_is_not_overwritten(self):
        chats.update_title(self.chat, collection_title=None, user_text="Kısa istek")
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, "Kısa istek")

        chats.update_title(self.chat, collection_title="Başka", user_text="Başka istek")
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, "Kısa istek")
        self.assertNotEqual(self.chat.title, DEFAULT_TITLE)


class HistoryTests(TestCase):
    def test_history_skips_errors_current_message_and_limits_to_six(self):
        chat = make_chat(make_user())
        for index in range(8):
            make_message(chat, "user" if index % 2 == 0 else "assistant", f"m{index}")
        make_message(chat, "assistant", "", error={"detail": "x", "code": "model_error"})
        current = make_message(chat, "user", "şimdiki")

        history = chats.recent_history(chat, before_id=current.pk)

        self.assertEqual([m.text for m in history], ["m2", "m3", "m4", "m5", "m6", "m7"])
