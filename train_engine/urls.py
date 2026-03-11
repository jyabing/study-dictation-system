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

    path(
        "course/<int:course_id>/",
        views.course_detail,
        name="course_detail"
    ),

    path(
        "lesson/create/<int:course_id>/",
        views.lesson_create,
        name="lesson_create"
    ),

    path(
        "lesson/<int:lesson_id>/",
        views.lesson_detail,
        name="lesson_detail"
    ),

    path(
        "sentence/create/<int:lesson_id>/",
        views.sentence_create,
        name="sentence_create"
    ),

    path(
        "sentence/<int:sentence_id>/",
        views.sentence_detail,
        name="sentence_detail"
    ),

    path(
        "question/create/<int:sentence_id>/",
        views.question_create,
        name="question_create"
    ),

    path(
        "question/<int:question_id>/edit/",
        views.question_edit,
        name="question_edit"
    ),

    path(
        "question/<int:question_id>/delete/",
        views.question_delete,
        name="question_delete"
    ),

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

    path(
        "api/train/transcribe/",
        views.transcribe_speaking_audio,
        name="transcribe_speaking_audio"
    ),

    path(
        "api/train/score-speaking/",
        views.score_speaking
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