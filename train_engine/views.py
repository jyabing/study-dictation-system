import re

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import Sentence, StudyLog, Question


# =========================
# 文本标准化
# =========================
def normalize_text(s: str) -> str:

    if not s:
        return ""

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
# Dashboard 首页
# =========================
def dashboard(request):

    return render(
        request,
        "train_engine/dashboard.html"
    )


# =========================
# 多题型训练页面
# =========================
def question_train_page(request):

    return render(request, "train_engine/question_train.html")


# =========================
# 课程句子
# =========================
def lesson_sentences(request, lesson_id):

    try:

        sentences = Sentence.objects.filter(
            lesson_id=lesson_id
        ).order_by("id")

        return JsonResponse({

            "sentences": [

                {
                    "id": s.id,
                    "text": s.text
                }

                for s in sentences

            ]

        })

    except Exception as e:

        return JsonResponse({

            "error": str(e)

        }, status=500)

# =========================
# 获取 Lesson 下的题目
# 支持 ?qtype=choice / cloze / qa / listening / speaking
# =========================
def lesson_questions(request, lesson_id):

    qtype = request.GET.get("qtype")

    questions = Question.objects.filter(
        sentence__lesson_id=lesson_id,
        is_active=True
    ).select_related("sentence").prefetch_related("options").order_by("sort_order", "id")

    if qtype:
        questions = questions.filter(qtype=qtype)

    return JsonResponse({
        "questions": [
            {
                "id": q.id,
                "sentence_id": q.sentence_id,
                "qtype": q.qtype,
                "question": q.question,
                "answer": q.answer,
                "pattern": q.pattern,
                "is_multiple_choice": q.is_multiple_choice,
                "options": [
                    {
                        "id": opt.id,
                        "text": opt.text,
                        "is_correct": opt.is_correct,
                    }
                    for opt in q.options.all()
                ]
            }
            for q in questions
        ]
    })


# =========================
# 新题型统一判题
# 目前支持：
# - choice
# - cloze
# - qa
# - listening
# - speaking
# =========================
@csrf_exempt
@require_POST
def check_question_answer(request):

    try:
        question_id = request.POST.get("question_id")

        if not question_id:
            return JsonResponse({"error": "question_id missing"}, status=400)

        q = Question.objects.select_related("sentence").prefetch_related("options").get(id=question_id)

        correct = False
        user_input_text = ""

        # 选择题
        if q.qtype == "choice":
            user_selected = request.POST.getlist("user_input")
            user_selected = [x.strip() for x in user_selected if x.strip()]

            correct_options = [opt.text for opt in q.options.filter(is_correct=True)]

            correct = set(user_selected) == set(correct_options)
            user_input_text = " | ".join(user_selected)

        # 问答 / 挖空 / 听力 / 朗读：先做基础文本对比
        else:
            user_input_text = request.POST.get("user_input", "").strip()

            expected = normalize_text(q.answer or "")
            got = normalize_text(user_input_text)

            # 问答题：如果配置了 pattern，先判断是否包含指定句型
            if q.qtype == "qa" and q.pattern:
                pattern_ok = normalize_text(q.pattern.replace("~", "").strip()) in got
                answer_ok = expected == got
                correct = pattern_ok and answer_ok
            else:
                correct = expected == got

        last_log = StudyLog.objects.filter(
            question=q
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

        intervals = [5, 30, 720, 1440, 4320, 10080]
        minutes = intervals[min(memory_level, len(intervals) - 1)]
        next_review = timezone.now() + timezone.timedelta(minutes=minutes)

        StudyLog.objects.create(
            sentence=q.sentence,
            question=q,
            user_input=user_input_text,
            correct=correct,
            memory_level=memory_level,
            wrong_count=wrong_count,
            next_review=next_review
        )

        return JsonResponse({
            "correct": correct,
            "expected": q.answer,
            "pattern": q.pattern,
            "memory_level": memory_level,
            "wrong_count": wrong_count,
            "next_review": next_review.isoformat(),
        })

    except Question.DoesNotExist:
        return JsonResponse({"error": "question not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)



# =========================
# 检查答案
# =========================
@csrf_exempt
@require_POST
def check_answer(request):

    try:

        sentence_id = request.POST.get("sentence_id")

        user_input = request.POST.get("user_input") or ""

        if not sentence_id:

            return JsonResponse({"error": "sentence_id missing"}, status=400)

        sentence = Sentence.objects.filter(id=sentence_id).first()

        if not sentence:
            return JsonResponse({"error": "sentence not found"}, status=404)

        expected = normalize_text(sentence.text)

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
            "expected": sentence.text,
            "expected": sentence.text

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
                    "text": s.text
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
                    "text": s.text
                }

                for s in sentences

            ]

        })

    except Exception as e:

        return JsonResponse({

            "error": str(e)

        }, status=500)