from django.db import models
from django.utils import timezone


# =========================
# Course
# =========================
class Course(models.Model):

    name_en = models.CharField(
        max_length=200,
        verbose_name="Course Name / 课程名称"
    )

    description = models.TextField(
        blank=True
    )

    class Meta:
        verbose_name = "Course / 课程"
        verbose_name_plural = "Courses / 课程"

    def __str__(self):
        return self.name_en


# =========================
# Lesson
# =========================
class Lesson(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons"
    )

    title_en = models.CharField(
        max_length=200
    )

    order = models.IntegerField(
        default=0
    )

    class Meta:
        verbose_name = "Lesson / 章节"
        verbose_name_plural = "Lessons / 章节"
        ordering = ["order"]

    def __str__(self):
        return self.title_en


# =========================
# Sentence
# =========================
class Sentence(models.Model):

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="sentences"
    )

    text_en = models.TextField()

    class Meta:
        verbose_name = "Sentence / 句子"
        verbose_name_plural = "Sentences / 句子"

    def __str__(self):
        return self.text_en[:50]


# =========================
# StudyLog
# =========================
class StudyLog(models.Model):

    sentence = models.ForeignKey(
        "Sentence",
        on_delete=models.CASCADE,
        related_name="study_logs"
    )

    user_input = models.TextField(
        blank=True
    )

    correct = models.BooleanField()

    # =========================
    # SRS 记忆等级
    # =========================
    memory_level = models.IntegerField(
        default=0,
        help_text="0-6 记忆等级"
    )

    # =========================
    # 下次复习时间
    # =========================
    next_review = models.DateTimeField(
        default=timezone.now
    )

    # =========================
    # 错误次数
    # =========================
    wrong_count = models.IntegerField(
        default=0
    )

    # =========================
    # 记录时间
    # =========================
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        verbose_name = "Study Log / 学习记录"
        verbose_name_plural = "Study Logs / 学习记录"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.sentence.text_en[:30]} ({'✓' if self.correct else '✗'})"