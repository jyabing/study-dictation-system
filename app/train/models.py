from django.db import models
from django.conf import settings


# =========================
# Book（书册）
# =========================
class Book(models.Model):

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    title = models.CharField(max_length=255)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


# =========================
# Lesson（章节）
# =========================
class Lesson(models.Model):

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="lessons"
    )

    title = models.CharField(max_length=255)

    order = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.book.title} - {self.title}"


# =========================
# Question（题目）
# =========================
class Question(models.Model):

    QUESTION_TYPES = [
        ("listen", "听"),
        ("speak", "说"),
        ("read_cloze", "读-填空"),
        ("read_choice", "读-选择"),
        ("write", "写"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    book = models.ForeignKey(Book, on_delete=models.CASCADE)

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPES
    )

    prompt_text = models.TextField()

    answer_text = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.question_type} - {self.prompt_text[:20]}"


# =========================
# QuestionMemory（记忆状态）
# =========================
class QuestionMemory(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE
    )

    memory_level = models.IntegerField(default=0)

    correct_streak = models.IntegerField(default=0)

    total_correct = models.IntegerField(default=0)

    total_wrong = models.IntegerField(default=0)

    next_review_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "question")

    def __str__(self):
        return f"{self.user} - {self.question_id} - Lv{self.memory_level}"