from django.core.management.base import BaseCommand
from django.db import transaction

from app.train.models import MemoryItem, Question, TrainingItem


class Command(BaseCommand):
    help = "根据现有 Question 初始化 MemoryItem，并关联现有 TrainingItem"

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        linked_count = 0
        already_linked_count = 0
        missing_question_count = 0

        questions = (
            Question.objects
            .select_related("lesson")
            .prefetch_related("training_items")
            .order_by("id")
        )

        for question in questions:
            memory_item, created = MemoryItem.objects.get_or_create(
                lesson_id=question.lesson_id,
                prompt_text=question.prompt_text,
                answer_text=question.answer_text,
                defaults={
                    "audio_url": question.audio_url,
                },
            )

            if created:
                created_count += 1
            else:
                existing_count += 1

            for training_item in question.training_items.all():
                if training_item.memory_item_id == memory_item.id:
                    already_linked_count += 1
                    continue

                training_item.memory_item = memory_item
                training_item.save(update_fields=["memory_item"])
                linked_count += 1

        missing_question_count = TrainingItem.objects.filter(
            question__isnull=True
        ).count()

        self.stdout.write(
            self.style.SUCCESS(
                "\n初始化完成\n"
                f"新建 MemoryItem：{created_count}\n"
                f"复用 MemoryItem：{existing_count}\n"
                f"新关联 TrainingItem：{linked_count}\n"
                f"原本已正确关联：{already_linked_count}\n"
                f"没有 Question 的 TrainingItem：{missing_question_count}\n"
                f"当前 MemoryItem 总数：{MemoryItem.objects.count()}\n"
            )
        )
