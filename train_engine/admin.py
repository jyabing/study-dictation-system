from django.contrib import admin
from .models import (
    Course,
    Lesson,
    Sentence,
    Question,
    ChoiceOption,
    StudyLog
)


# =========================
# Inline
# =========================
class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("qtype", "question", "answer", "pattern", "is_multiple_choice", "option_count", "is_active")
    show_change_link = True


class ChoiceOptionInline(admin.TabularInline):
    model = ChoiceOption
    extra = 0
    fields = ("text", "is_correct", "is_auto_generated")
    readonly_fields = ("is_auto_generated",)


# =========================
# Course
# =========================
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "name_en")
    search_fields = ("name", "name_en")


# =========================
# Lesson
# =========================
@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "title_en", "course", "order")
    list_filter = ("course",)
    ordering = ("course", "order")


# =========================
# Sentence
# =========================
@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "text", "translation", "order")
    list_filter = ("lesson",)
    search_fields = ("text", "translation")
    inlines = [QuestionInline]


# =========================
# Question
# =========================
@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "qtype", "sentence", "short_question", "is_active", "is_auto_generated")
    list_filter = ("qtype", "is_active", "is_multiple_choice")
    search_fields = ("question", "answer", "pattern", "sentence__text")
    inlines = [ChoiceOptionInline]

    fieldsets = (
        ("基础信息", {
            "fields": ("sentence", "qtype", "question", "answer", "pattern")
        }),
        ("挖空题", {
            "fields": ("blank_mode",),
            "classes": ("collapse",)
        }),
        ("选择题", {
            "fields": ("is_multiple_choice", "option_count", "manual_distractors"),
            "classes": ("collapse",)
        }),
        ("听力 / 朗读", {
            "fields": ("audio",),
            "classes": ("collapse",)
        }),
        ("其他", {
            "fields": ("is_active", "is_auto_generated", "sort_order"),
            "classes": ("collapse",)
        }),
    )

    def short_question(self, obj):
        return (obj.question or "")[:40]


# =========================
# ChoiceOption
# =========================
@admin.register(ChoiceOption)
class ChoiceOptionAdmin(admin.ModelAdmin):
    list_display = ("id", "question", "text", "is_correct", "is_auto_generated")
    list_filter = ("is_correct", "is_auto_generated")


# =========================
# StudyLog
# =========================
@admin.register(StudyLog)
class StudyLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "question",
        "sentence",
        "correct",
        "memory_level",
        "wrong_count",
        "next_review",
        "created_at",
    )
    list_filter = ("correct",)
    search_fields = ("sentence__text", "question__question", "user_input")