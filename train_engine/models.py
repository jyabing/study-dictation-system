from django.db import models


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