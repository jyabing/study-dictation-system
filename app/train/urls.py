from django.urls import path
from django.contrib.auth import views as auth_views

from .views.book_views import (
    dashboard, book_create, active_training_books, book_detail, book_edit, lesson_edit,
    book_delete_confirm, book_delete_submit,
    lesson_delete_confirm, lesson_delete_submit,
)
from .views.train_views import (
    book_train,
    book_train_api,
    lesson_train,
    lesson_train_api,
    dictation_book_check,
    dictation_lesson_check,
    dictation_book_start,
    dictation_lesson_start,
    asr_transcribe_api,
    practice_player_page,
    practice_library_page,
    practice_playlist_create,
    practice_playlist_update,
    practice_playlist_delete,
    practice_track_upload,
    practice_track_update,
    practice_track_shadow_caption_save,
    practice_track_delete,
    practice_segment_save,
    practice_segment_update,
    practice_segment_delete,
    stats_page,
    builder_page,
    builder_save,
    set_daily_limit,
    question_edit,
    lesson_question_list,
    question_delete,
    book_train_manual_upgrade,
    lesson_train_manual_upgrade,
    global_due_train,
    global_due_train_api,
    global_due_train_manual_upgrade,
    global_overdue_train,
    global_overdue_train_api,
    global_overdue_train_manual_upgrade,
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
    path("practice-player/", practice_player_page, name="practice-player"),
    path("practice-player/track/<int:track_id>/", practice_player_page, name="practice-player-track"),
    path("practice-player/segment/<int:segment_id>/", practice_player_page, name="practice-player-segment"),
    path("practice-library/", practice_library_page, name="practice-library"),
    path("practice-library/playlist/create/", practice_playlist_create, name="practice-playlist-create"),
    path("practice-library/playlist/<int:playlist_id>/update/", practice_playlist_update, name="practice-playlist-update"),
    path("practice-library/playlist/<int:playlist_id>/delete/", practice_playlist_delete, name="practice-playlist-delete"),
    path("practice-library/playlist/<int:playlist_id>/track/upload/", practice_track_upload, name="practice-track-upload"),
    path("practice-library/track/<int:track_id>/update/", practice_track_update, name="practice-track-update"),
    path("practice-library/track/<int:track_id>/shadow-caption/save/", practice_track_shadow_caption_save, name="practice-track-shadow-caption-save"),
    path("practice-library/track/<int:track_id>/segment/save/", practice_segment_save, name="practice-segment-save"),
    path("practice-library/track/<int:track_id>/delete/", practice_track_delete, name="practice-track-delete"),
    path("practice-library/segment/<int:segment_id>/update/", practice_segment_update, name="practice-segment-update"),
    path("practice-library/segment/<int:segment_id>/delete/", practice_segment_delete, name="practice-segment-delete"),

    path("book/<int:book_id>/", book_detail, name="book-detail"),
    path("book/create/", book_create, name="book-create"),
    path("book/<int:book_id>/edit/", book_edit, name="book-edit"),

    # Book + Lesson
    path("book/<int:book_id>/train/", book_train, name="book-train"),
    path("dictation/book/<int:book_id>/check/", dictation_book_check, name="dictation-book-check"),
    path("dictation/book/<int:book_id>/start/", dictation_book_start, name="dictation-book-start"),
    path("dictation/lesson/<int:lesson_id>/check/", dictation_lesson_check, name="dictation-lesson-check"),
    path("dictation/lesson/<int:lesson_id>/start/", dictation_lesson_start, name="dictation-lesson-start"),
    path("api/book/<int:book_id>/train/", book_train_api, name="book-train-api"),
    path("api/book/<int:book_id>/train/manual-upgrade/", book_train_manual_upgrade, name="book-train-manual-upgrade"),
    path("api/asr/transcribe/", asr_transcribe_api, name="asr-transcribe-api"),

    # Global Train
    path("train/global/due/", global_due_train, name="global-due-train"),
    path("api/train/global/due/", global_due_train_api, name="global-due-train-api"),
    path(
        "api/train/global/due/manual-upgrade/",
        global_due_train_manual_upgrade,
        name="global-due-train-manual-upgrade"
    ),

    path("train/global/overdue/", global_overdue_train, name="global-overdue-train"),
    path("api/train/global/overdue/", global_overdue_train_api, name="global-overdue-train-api"),
    path(
        "api/train/global/overdue/manual-upgrade/",
        global_overdue_train_manual_upgrade,
        name="global-overdue-train-manual-upgrade"
    ),

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
    path("api/lesson/<int:lesson_id>/manual-upgrade/", lesson_train_manual_upgrade, name="lesson-train-manual-upgrade"),
    path("set-daily-limit/", set_daily_limit),
    path("stats/", stats_page, name="stats-page"),
    path("builder/", builder_page, name="builder-page"),
    path("builder/save/", builder_save, name="builder-save"),
]