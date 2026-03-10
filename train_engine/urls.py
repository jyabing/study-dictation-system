from django.urls import path
from . import views

urlpatterns = [

    # =========================
    # Dashboard
    # =========================
    path("", views.dashboard, name="dashboard"),

    # =========================
    # 页面
    # =========================
    path("dictation/", views.dictation_page, name="dictation_page"),
    path("question-train/", views.question_train_page, name="question_train_page"),
    path("courses/", views.course_list, name="course_list"),
    path("course/create/", views.course_create, name="course_create"),

    # =========================
    # Lesson API
    # =========================
    path(
        "lesson/<int:lesson_id>/sentences/",
        views.lesson_sentences,
        name="lesson_sentences"
    ),

    path(
        "lesson/<int:lesson_id>/questions/",
        views.lesson_questions,
        name="lesson_questions"
    ),

    # =========================
    # Dictation Check
    # =========================
    path(
        "api/train/check/",
        views.check_answer,
        name="check_answer"
    ),

    path(
        "api/train/check_question/",
        views.check_question_answer,
        name="check_question_answer"
    ),

    # =========================
    # Wrong Review
    # =========================
    path(
        "api/review/wrong/",
        views.wrong_sentences,
        name="wrong_sentences"
    ),

    # =========================
    # Due Review (SRS)
    # =========================
    path(
        "api/review/due/",
        views.review_due_sentences,
        name="review_due_sentences"
    ),
]