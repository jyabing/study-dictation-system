from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponse
import csv

from .models import (
    Course,
    Lesson,
    Sentence,
    Question,
    ChoiceOption,
    StudyLog,
    WrongQuestionLog
)

from .services.question_engine import sync_question_content


# =========================
# ChoiceOption Inline
# =========================
class ChoiceOptionInline(admin.TabularInline):
    model = ChoiceOption
    extra = 0

    fields = (
        "letter",
        "text",
        "is_correct",
        "order"
    )


# =========================
# Question Inline
# =========================
class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0

    fields = (
        "qtype",
        "question",
        "answer",
        "pattern",
        "blank_mode",
        "is_multiple_choice",
        "option_count",
        "manual_distractors",
        "audio",
        "is_active",
        "is_auto_generated",
        "sort_order"
    )


# =========================
# Course Admin
# =========================
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name",
        "name_en"
    )

    search_fields = (
        "name",
        "name_en"
    )


# =========================
# Lesson Admin
# =========================
@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "title",
        "course",
        "order"
    )

    list_filter = (
        "course",
    )

    search_fields = (
        "title",
    )

    ordering = (
        "order",
        "id"
    )


# =========================
# Sentence Admin
# =========================
@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "text",
        "lesson",
        "difficulty",
        "order",
        "generate_questions_button"
    )

    list_filter = (
        "lesson",
        "difficulty"
    )

    search_fields = (
        "text",
        "translation"
    )

    ordering = (
        "order",
        "id"
    )

    inlines = [
        QuestionInline
    ]

    actions = [
        "generate_questions"
    ]

    # =========================
    # 一键生成题目按钮
    # =========================
    def generate_questions_button(self, obj):
        return format_html(
            '<a class="button" href="/admin/train_engine/sentence/{}/change/">编辑</a>',
            obj.id
        )

    generate_questions_button.short_description = "编辑"


    # =========================
    # 批量生成题目
    # =========================
    def generate_questions(self, request, queryset):

        for sentence in queryset:

            qtypes = [
                "cloze",
                "choice",
                "listening",
                "speaking",
                "qa"
            ]

            for qt in qtypes:

                q, created = Question.objects.get_or_create(
                    sentence=sentence,
                    qtype=qt,
                    defaults={
                        "is_auto_generated": True
                    }
                )

                if created:
                    sync_question_content(q)

        self.message_user(request, "题目生成完成")

    generate_questions.short_description = "自动生成题目"


# =========================
# Question Admin
# =========================
@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "qtype",
        "sentence",
        "is_active",
        "is_auto_generated",
        "sort_order"
    )

    list_filter = (
        "qtype",
        "is_active",
        "is_auto_generated"
    )

    search_fields = (
        "question",
        "answer"
    )

    ordering = (
        "sort_order",
        "id"
    )

    inlines = [
        ChoiceOptionInline
    ]


# =========================
# ChoiceOption Admin
# =========================
@admin.register(ChoiceOption)
class ChoiceOptionAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "question",
        "letter",
        "text",
        "is_correct",
        "order"
    )

    list_filter = (
        "is_correct",
    )

    search_fields = (
        "text",
    )

    ordering = (
        "order",
        "id"
    )

    actions = [
        "auto_letter"
    ]

    # 自动 ABCD
    def auto_letter(self, request, queryset):

        letters = ["A", "B", "C", "D", "E", "F"]

        for q in queryset.values_list("question", flat=True).distinct():

            opts = ChoiceOption.objects.filter(
                question=q
            ).order_by("order", "id")

            for i, opt in enumerate(opts):

                if i < len(letters):
                    opt.letter = letters[i]
                    opt.save()

        self.message_user(request, "选项字母已自动生成")

    auto_letter.short_description = "自动生成 ABCD"


# =========================
# StudyLog Admin
# =========================
@admin.register(StudyLog)
class StudyLogAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "question",
        "user_input",
        "correct",
        "memory_level",
        "next_review",
        "created_at"
    )

    list_filter = (
        "correct",
        "memory_level"
    )

    search_fields = (
        "user_input",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "created_at",
    )


# =========================
# WrongQuestion Admin
# =========================
@admin.register(WrongQuestionLog)
class WrongQuestionLogAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "question",
        "wrong_count",
        "last_wrong",
        "is_mastered"
    )

    list_filter = (
        "is_mastered",
    )

    ordering = (
        "-last_wrong",
    )


# =========================
# CSV 导出 Sentence
# =========================
@admin.action(description="导出 Sentence CSV")
def export_sentences(modeladmin, request, queryset):

    response = HttpResponse(
        content_type="text/csv"
    )

    response["Content-Disposition"] = "attachment; filename=sentences.csv"

    writer = csv.writer(response)

    writer.writerow([
        "lesson",
        "text",
        "translation"
    ])

    for s in queryset:
        writer.writerow([
            s.lesson.title,
            s.text,
            s.translation
        ])

    return response