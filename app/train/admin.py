from django.contrib import admin
from .models import Book, Lesson, Question, QuestionMemory


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "created_at")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "book", "order")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "question_type", "book", "lesson")


@admin.register(QuestionMemory)
class QuestionMemoryAdmin(admin.ModelAdmin):
    list_display = ("user", "question", "memory_level")