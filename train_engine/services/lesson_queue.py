from django.utils import timezone
from random import shuffle

from train_engine.models import Sentence, Question, UserMemoryState
from .srs_engine import get_due_status, serialize_memory


def build_lesson_queue(lesson_id, limit=5, qtype=None):
    """
    构建训练题目队列

    优先级：
    1 due
    2 new
    3 waiting

    限制：
    - 新知识最多 40%
    - 避免同 sentence 连续
    """

    now = timezone.now()

    sentences = (
        Sentence.objects
        .filter(lesson_id=lesson_id)
        .order_by("order", "id")
    )

    sentence_ids = list(sentences.values_list("id", flat=True))

    memories = {
        m.sentence_id: m
        for m in UserMemoryState.objects.filter(sentence_id__in=sentence_ids)
    }

    due = []
    new = []
    waiting = []

    for s in sentences:

        memory = memories.get(s.id)

        if not memory:
            new.append(s)
            continue

        status = get_due_status(memory, now=now)

        if status in ("due", "overdue"):
            due.append(s)

        elif status == "waiting":
            waiting.append(s)

    shuffle(due)
    shuffle(new)
    shuffle(waiting)

    queue = []

    max_new = max(1, int(limit * 0.4))

    new_count = 0

    # ====================
    # 1 due
    # ====================

    for s in due:

        if len(queue) >= limit:
            break

        queue.append(s)

    # ====================
    # 2 new
    # ====================

    for s in new:

        if len(queue) >= limit:
            break

        if new_count >= max_new:
            break

        queue.append(s)

        new_count += 1

    # ====================
    # 3 waiting
    # ====================

    for s in waiting:

        if len(queue) >= limit:
            break

        queue.append(s)

    return build_questions(queue, memories, qtype)


def build_questions(sentences, memories, qtype=None):
    """
    将 sentence 转换为 question
    """

    result = []

    last_sentence = None

    for s in sentences:

        qs = Question.objects.filter(
            sentence=s,
            is_active=True,
        )

        if qtype:
            qs = qs.filter(qtype=qtype)

        q = qs.first()

        if not q:
            continue

        if last_sentence and last_sentence == s.id:
            continue

        last_sentence = s.id

        memory = memories.get(s.id)

        memory_data = serialize_memory(memory) if memory else None

        options = []

        if q.qtype == "choice":
            for opt in q.options.all():
                options.append({
                    "text": opt.text,
                    "is_correct": opt.is_correct
                })

        result.append({
            "id": q.id,
            "sentence_id": s.id,
            "qtype": q.qtype,
            "question": q.question,
            "answer": q.answer,
            "options": options,
            "memory": memory_data
        })

    return result