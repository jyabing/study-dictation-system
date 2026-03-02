from django.urls import path
from . import views

urlpatterns = [
    path("lesson/<int:lesson_id>/sentences/", views.lesson_sentences, name="lesson_sentences"),
    path("check/", views.check_answer, name="check_answer"),
    path("dictation/", views.dictation_page, name="dictation_page"),
]