import re

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import Sentence, StudyLog


# =========================
# 文本标准化
# =========================
def normalize_text(s: str) -> str:

    s = s.lower()

    s = re.sub(r"[^\w\s]", "", s)

    s = re.sub(r"\s+", " ", s).strip()

    return s


# =========================
# 页面
# =========================
def dictation_page(request):

    return render(request, "train_engine/dictation.html")


# =========================
# 课程句子
# =========================
def lesson_sentences(request, lesson_id):

    sentences = Sentence.objects.filter(
        lesson_id=lesson_id
    ).order_by("id")

    return JsonResponse({

        "sentences": [

            {
                "id": s.id,
                "text_en": s.text_en
            }

            for s in sentences

        ]

    })


# =========================
# 检查答案
# =========================
@csrf_exempt
@require_POST
def check_answer(request):

    try:

        sentence_id = request.POST.get("sentence_id")

        user_input = request.POST.get("user_input", "")

        if not sentence_id:

            return JsonResponse({"error": "sentence_id missing"}, status=400)

        sentence = Sentence.objects.get(id=sentence_id)

        expected = normalize_text(sentence.text_en)

        user = normalize_text(user_input)

        correct = expected == user

        # 查找最近记录
        last_log = StudyLog.objects.filter(
            sentence=sentence
        ).order_by("-created_at").first()

        memory_level = 0
        wrong_count = 0

        if last_log:

            memory_level = last_log.memory_level
            wrong_count = last_log.wrong_count

        if correct:

            memory_level += 1

        else:

            memory_level = 0
            wrong_count += 1

        # 简单艾宾浩斯间隔
        intervals = [5, 30, 720, 1440, 4320, 10080]

        minutes = intervals[min(memory_level, len(intervals)-1)]

        next_review = timezone.now() + timezone.timedelta(minutes=minutes)

        StudyLog.objects.create(

            sentence=sentence,

            user_input=user_input,

            correct=correct,

            memory_level=memory_level,

            wrong_count=wrong_count,

            next_review=next_review

        )

        return JsonResponse({

            "correct": correct,
            "expected": sentence.text_en

        })

    except Exception as e:

        return JsonResponse({

            "error": str(e)

        }, status=500)


# =========================
# 错题复习
# =========================
def wrong_sentences(request):

    try:

        logs = StudyLog.objects.filter(correct=False)

        sentence_ids = logs.values_list(
            "sentence_id",
            flat=True
        ).distinct()

        sentences = Sentence.objects.filter(
            id__in=sentence_ids
        )

        return JsonResponse({

            "sentences": [

                {
                    "id": s.id,
                    "text_en": s.text_en
                }

                for s in sentences

            ]

        })

    except Exception as e:

        return JsonResponse({

            "error": str(e)

        }, status=500)


# =========================
# 到期复习
# =========================
def review_due_sentences(request):

    try:

        now = timezone.now()

        logs = StudyLog.objects.filter(

            next_review__lte=now

        )

        sentence_ids = logs.values_list(
            "sentence_id",
            flat=True
        ).distinct()

        sentences = Sentence.objects.filter(
            id__in=sentence_ids
        )

        return JsonResponse({

            "sentences": [

                {
                    "id": s.id,
                    "text_en": s.text_en
                }

                for s in sentences

            ]

        })

    except Exception as e:

        return JsonResponse({

            "error": str(e)

        }, status=500)