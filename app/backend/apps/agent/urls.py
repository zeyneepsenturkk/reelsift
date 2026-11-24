from django.urls import path

from apps.agent import views

app_name = "agent"

urlpatterns = [
    path("chats/<int:chat_id>/messages/stream", views.stream_message, name="stream"),
]
