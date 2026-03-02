from django.contrib import admin
from .models import Course, Lesson, Sentence, Word, StudyLog


# ===============================
# Sentence Inline（在 Lesson 页面内直接编辑句子）
# ===============================
class SentenceInline(admin.TabularInline):
    model = Sentence
    extra = 1
    fields = ("text_en", "text_zh", "text_ja")


# ===============================
# Course Admin（课程）
# ===============================
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name_en",)
    search_fields = ("name_en",)


# ===============================
# Lesson Admin（章节）
# ===============================
@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title_en", "course", "order")
    list_filter = ("course",)
    search_fields = ("title_en",)

    inlines = [SentenceInline]

    fields = ("title_en", "course", "order")


# ===============================
# Sentence Admin（句子）
# ===============================
@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ("text_en_short", "text_zh_short", "lesson")
    search_fields = ("text_en", "text_zh")

    def text_en_short(self, obj):
        return (obj.text_en or "")[:30]
    text_en_short.short_description = "English"

    def text_zh_short(self, obj):
        return (obj.text_zh or "")[:30]
    text_zh_short.short_description = "中文"


# ===============================
# Word Admin（单词）
# ===============================
@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ("text", "meaning_en_short", "meaning_zh_short")
    search_fields = ("text", "meaning_en", "meaning_zh")

    def meaning_en_short(self, obj):
        return (obj.meaning_en or "")[:30]
    meaning_en_short.short_description = "English"

    def meaning_zh_short(self, obj):
        return (obj.meaning_zh or "")[:30]
    meaning_zh_short.short_description = "中文"


# ===============================
# StudyLog Admin（学习记录）
# ===============================
@admin.register(StudyLog)
class StudyLogAdmin(admin.ModelAdmin):
    list_display = ("word", "correct", "review_time")
    list_filter = ("correct",)