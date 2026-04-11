from django.urls import path
from django.contrib.auth import views as auth_views

from .views.book_views import (
    dashboard, book_detail, book_edit, lesson_edit,
    book_delete_confirm, book_delete_submit,
    lesson_delete_confirm, lesson_delete_submit,
)
from .views.train_views import (
    book_train,
    book_train_api,
    lesson_train,
    lesson_train_api,
    stats_page,
    builder_page,
    builder_save,
    set_daily_limit,
    question_edit,
    lesson_question_list,
    question_delete,
)

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="train/login.html",
            redirect_authenticated_user=True
        ),
        name="login"
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout"
    ),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="train/password_change.html"
        ),
        name="password_change"
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="train/password_change_done.html"
        ),
        name="password_change_done"
    ),

    path("", dashboard, name="dashboard"),

    # Book + Lesson
    path("book/<int:book_id>/", book_detail, name="book-detail"),
    path("book/<int:book_id>/edit/", book_edit, name="book-edit"),

    path("book/<int:book_id>/train/", book_train, name="book-train"),
    path("api/book/<int:book_id>/train/", book_train_api, name="book-train-api"),

    path("lesson/<int:lesson_id>/edit/", lesson_edit, name="lesson-edit"),
    path("question/<int:question_id>/edit/", question_edit, name="question-edit"),
    path("question/<int:question_id>/delete/", question_delete, name="question-delete"),

    path("book/<int:book_id>/delete/", book_delete_confirm, name="book-delete-confirm"),
    path("book/<int:book_id>/delete/submit/", book_delete_submit, name="book-delete-submit"),

    path("lesson/<int:lesson_id>/delete/", lesson_delete_confirm, name="lesson-delete-confirm"),
    path("lesson/<int:lesson_id>/delete/submit/", lesson_delete_submit, name="lesson-delete-submit"),


    # Lesson + Train
    path("lesson/<int:lesson_id>/", lesson_train, name="lesson-train"),
    path("lesson/<int:lesson_id>/questions/", lesson_question_list, name="lesson-question-list"),
    path("api/lesson/<int:lesson_id>/", lesson_train_api, name="lesson-train-api"),
    path("set-daily-limit/", set_daily_limit),
    path("stats/", stats_page, name="stats-page"),
    path("builder/", builder_page, name="builder-page"),
    path("builder/save/", builder_save, name="builder-save"),
]