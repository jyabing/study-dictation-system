from django.contrib import admin
from .models import Course, Lesson, Sentence, StudyLog


class SentenceInline(admin.TabularInline):
    model = Sentence
    extra = 1
    fields = ("text_en",)
    ordering = ("id",)


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ("title_en", "order")
    ordering = ("order",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("id", "name_en")
    search_fields = ("name_en",)
    ordering = ("name_en",)
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "title_en", "course", "order")
    list_filter = ("course",)
    search_fields = ("title_en",)
    ordering = ("course", "order")
    inlines = [SentenceInline]


@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ("id", "text_en", "lesson")
    list_filter = ("lesson",)
    search_fields = ("text_en",)
    ordering = ("lesson", "id")


@admin.register(StudyLog)
class StudyLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sentence",
        "correct",
        "memory_level",
        "next_review",
        "wrong_count",
        "created_at",
    )
    list_filter = ("correct", "memory_level")
    search_fields = ("sentence__text_en", "user_input")
    ordering = ("-created_at",)