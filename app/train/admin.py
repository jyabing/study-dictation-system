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
    list_display = ("id", "question", "item_type")
    list_filter = ("item_type",)


@admin.register(QuestionMemory)
class QuestionMemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "question", "memory_level", "next_review_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "xp", "level", "streak")