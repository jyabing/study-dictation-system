from django.contrib import admin
from .models import (
    Book,
    Lesson,
    Question,
    TrainingItem,
    QuestionMemory,
    UserProfile
)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "book", "order")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "prompt_text")


@admin.register(TrainingItem)
class TrainingItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "question",
        "item_type",
        "instruction_text_short",
        "source_text_short",
        "target_answer_short",
        "language",
        "answer_type",
        "difficulty",
        "is_active",
        "sort_order",
    )

    list_filter = (
        "item_type",
        "language",
        "answer_type",
        "grading_mode",
        "cloze_mode",
        "is_active",
        "difficulty",
    )

    search_fields = (
        "instruction_text",
        "source_text",
        "target_answer",
        "prompt_text",
        "source_reference",
        "notes",
    )

    readonly_fields = (
        "created_at",
    )

    fieldsets = (
        ("旧结构（兼容保留）", {
            "fields": (
                "question",
                "item_type",
                "prompt_text",
                "audio_file",
                "reveal_text_on_wrong",
            )
        }),
        ("新结构：核心三要素", {
            "fields": (
                "instruction_text",
                "source_text",
                "target_answer",
            )
        }),
        ("判题与解释", {
            "fields": (
                "accepted_answers",
                "explanation",
                "grading_mode",
            )
        }),
        ("训练控制", {
            "fields": (
                "answer_type",
                "language",
                "enabled_modes",
                "difficulty",
            )
        }),
        ("克漏字与选择题", {
            "fields": (
                "manual_cloze_text",
                "cloze_mode",
                "auto_cloze_enabled",
                "cloze_text",
                "cloze_answers",
                "choices",
                "correct_answers",
            )
        }),
        ("音频", {
            "fields": (
                "source_audio",
                "target_audio",
            )
        }),
        ("管理信息", {
            "fields": (
                "tags",
                "source_reference",
                "notes",
                "is_active",
                "sort_order",
                "created_at",
            )
        }),
    )

    def instruction_text_short(self, obj):
        return (obj.instruction_text or "")[:20]
    instruction_text_short.short_description = "提示短语"

    def source_text_short(self, obj):
        return (obj.source_text or "")[:24]
    source_text_short.short_description = "题干"

    def target_answer_short(self, obj):
        return (obj.target_answer or "")[:24]
    target_answer_short.short_description = "回答"


@admin.register(QuestionMemory)
class QuestionMemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "question", "memory_level", "next_review_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "xp", "level", "streak")