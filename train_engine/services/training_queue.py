from django.utils import timezone
from train_engine.services.srs_engine import get_due_status


def build_training_queue(questions, memory_map):
    """
    构建训练队列

    优先级：

    1 错题
    2 overdue
    3 due
    4 waiting
    5 new
    """

    wrong = []
    overdue = []
    due = []
    waiting = []
    new = []

    now = timezone.now()

    for q in questions:

        memory = memory_map.get(q.sentence_id)

        if not memory:
            new.append(q)
            continue

        status = get_due_status(memory, now=now)

        if status == "overdue":
            overdue.append(q)

        elif status == "due":
            due.append(q)

        elif status == "waiting":
            waiting.append(q)

        elif status == "new":
            new.append(q)

    queue = []

    queue.extend(overdue)
    queue.extend(due)
    queue.extend(waiting)
    queue.extend(new)

    return queue