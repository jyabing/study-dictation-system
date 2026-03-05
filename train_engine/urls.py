from django.urls import path
from . import views
from .views import check_answer

urlpatterns = [
    path("", views.dictation_page, name="home"),   # 关键这一行
    path("dictation/", views.dictation_page, name="dictation_page"),
    path("lesson/<int:lesson_id>/sentences/", views.lesson_sentences, name="lesson_sentences"),
    path("check/", views.check_answer, name="check_answer"),
    path("api/train/check/", check_answer),
]