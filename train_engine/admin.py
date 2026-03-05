from django.contrib import admin
from .models import Course, Lesson, Sentence


# =========================
# Sentence Inline
# =========================
class SentenceInline(admin.TabularInline):
    model = Sentence
    extra = 1
    fields = ("text_en",)
    ordering = ("id",)


# =========================
# Lesson Inline
# =========================
class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ("title_en", "order")
    ordering = ("order",)


# =========================
# Course Admin
# =========================
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name_en",
    )

    search_fields = (
        "name_en",
    )

    ordering = (
        "name_en",
    )

    inlines = [
        LessonInline
    ]


# =========================
# Lesson Admin
# =========================
@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "title_en",
        "course",
        "order",
    )

    list_filter = (
        "course",
    )

    search_fields = (
        "title_en",
    )

    ordering = (
        "course",
        "order",
    )

    inlines = [
        SentenceInline
    ]


# =========================
# Sentence Admin
# =========================
@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "text_en",
        "lesson",
    )

    list_filter = (
        "lesson",
    )

    search_fields = (
        "text_en",
    )

    ordering = (
        "lesson",
        "id",
    )