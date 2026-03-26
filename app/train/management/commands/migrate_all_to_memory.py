from django.core.management.base import BaseCommand
from app.train.models import (
    Question,
    MemoryItem,
    TrainingItem,
    QuestionMemory
)


class Command(BaseCommand):
    help = "Full migration: Question → MemoryItem → TrainingItem → Memory"

    def handle(self, *args, **kwargs):

        print("🚀 开始迁移...")

        # =========================
        # 1️⃣ Question → MemoryItem
        # =========================
        for q in Question.objects.all():

            memory, created = MemoryItem.objects.get_or_create(
                lesson=q.lesson,
                prompt_text=q.prompt_text,
                answer_text=q.answer_text,
                defaults={
                    "audio_url": q.audio_url
                }
            )

            # =========================
            # 2️⃣ 创建 TrainingItem
            # =========================

            # Cloze（填空）
            TrainingItem.objects.get_or_create(
                memory=memory,
                item_type="read_cloze",
                defaults={
                    "cloze_text": q.prompt_text,
                    "cloze_answers": [q.answer_text],
                    "reveal_text_on_wrong": True,
                }
            )

            # Choice（选择题）
            TrainingItem.objects.get_or_create(
                memory=memory,
                item_type="read_choice",
                defaults={
                    "prompt_text": q.prompt_text,
                    "choices": [
                        q.answer_text,
                        "选项A",
                        "选项B",
                        "选项C"
                    ],
                    "correct_answers": [q.answer_text],
                }
            )

        print("✅ MemoryItem + TrainingItem 创建完成")

        # =========================
        # 🔥 修复版：QuestionMemory → item
        # =========================
        for m in QuestionMemory.objects.filter(item__isnull=True):

            if not m.question:
                continue

            # 🔥 更宽松匹配
            memory = MemoryItem.objects.filter(
                lesson=m.question.lesson
            ).filter(
                prompt_text__icontains=m.question.prompt_text[:10]
            ).first()

            if not memory:
                print(f"❌ 找不到 MemoryItem: Q{m.question.id}")
                continue

            items = TrainingItem.objects.filter(memory=memory)

            for item in items:
                QuestionMemory.objects.get_or_create(
                    user=m.user,
                    item=item,
                    defaults={
                        "memory_level": m.memory_level,
                        "next_review_at": m.next_review_at,
                        "correct_streak": m.correct_streak,
                        "total_correct": m.total_correct,
                        "total_wrong": m.total_wrong,
                        "last_review_at": m.last_review_at,
                    }
                )

        print("✅ QuestionMemory 迁移完成")

        print("🎉 全部迁移完成！")