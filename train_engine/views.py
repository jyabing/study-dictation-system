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
# 课程列表（课程管理）
# =========================
def course_list(request):

    from .models import Course, Lesson, Question

    courses = Course.objects.all().order_by("-id")

    course_data = []

    for c in courses:

        lesson_count = Lesson.objects.filter(course=c).count()

        question_count = Question.objects.filter(
            sentence__lesson__course=c
        ).count()

        course_data.append({
            "course": c,
            "lesson_count": lesson_count,
            "question_count": question_count
        })

    return render(
        request,
        "train_engine/course_list.html",
        {
            "courses": course_data
        }
    )

# =========================
# 新增课程
# =========================
def course_create(request):

    from .models import Course

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        is_public = request.POST.get("is_public") == "on"

        if name:

            Course.objects.create(
                name=name,
                description=description
            )

            from django.shortcuts import redirect
            return redirect("/courses/")

    return render(
        request,
        "train_engine/course_create.html"
    )

# =========================
# 课程详情（章节管理）
# =========================
def course_detail(request, course_id):

    from .models import Course, Lesson

    course = Course.objects.get(id=course_id)

    lessons = Lesson.objects.filter(
        course=course
    ).order_by("order")

    lesson_data = []

    for l in lessons:

        question_count = l.sentences.count()

        lesson_data.append({

            "id": l.id,
            "title": l.title,
            "question_count": question_count

        })

    return render(
        request,
        "train_engine/course_detail.html",
        {
            "course": course,
            "lessons": lesson_data
        }
    )

# =========================
# 新增章节
# =========================
def lesson_create(request, course_id):

    from .models import Course, Lesson
    from django.shortcuts import redirect

    course = Course.objects.get(id=course_id)

    if request.method == "POST":

        title = request.POST.get("title", "").strip()
        order = request.POST.get("order", "0")

        if title:

            Lesson.objects.create(
                course=course,
                title=title,
                order=int(order)
            )

            return redirect(f"/course/{course_id}/")

    return render(
        request,
        "train_engine/lesson_create.html",
        {
            "course": course
        }
    )

# =========================
# 章节题目管理
# =========================
def lesson_detail(request, lesson_id):

    from .models import Lesson, Sentence, Question

    lesson = Lesson.objects.get(id=lesson_id)

    sentences = Sentence.objects.filter(
        lesson=lesson
    ).order_by("order")

    data = []

    for s in sentences:

        q_count = Question.objects.filter(
            sentence=s
        ).count()

        data.append({
            "id": s.id,
            "text": s.text,
            "translation": s.translation,
            "question_count": q_count
        })

    return render(
        request,
        "train_engine/lesson_detail.html",
        {
            "lesson": lesson,
            "sentences": data
        }
    )

# =========================
# 新增句子
# =========================
def sentence_create(request, lesson_id):

    from .models import Lesson, Sentence, Question
    from django.shortcuts import redirect

    lesson = Lesson.objects.get(id=lesson_id)

    if request.method == "POST":

        text = request.POST.get("text", "").strip()
        translation = request.POST.get("translation", "").strip()

        if text:

            sentence = Sentence.objects.create(
                lesson=lesson,
                text=text,
                translation=translation
            )

            # 自动生成题目
            Question.objects.create(
                sentence=sentence,
                qtype="cloze"
            )

            Question.objects.create(
                sentence=sentence,
                qtype="choice"
            )

            Question.objects.create(
                sentence=sentence,
                qtype="listening"
            )

            Question.objects.create(
                sentence=sentence,
                qtype="speaking"
            )

            return redirect(f"/lesson/{lesson_id}/")

    return render(
        request,
        "train_engine/sentence_create.html",
        {
            "lesson": lesson
        }
    )

# =========================
# 句子题目管理
# =========================
def sentence_detail(request, sentence_id):

    from .models import Sentence, Question

    sentence = Sentence.objects.get(id=sentence_id)

    questions = Question.objects.filter(
        sentence=sentence
    ).prefetch_related("options").order_by("sort_order", "id")

    data = []

    for q in questions:

        options = []

        for o in q.options.all():

            options.append({
                "id": o.id,
                "text": o.text,
                "is_correct": o.is_correct
            })

        data.append({

            "id": q.id,
            "qtype": q.qtype,
            "question": q.question,
            "answer": q.answer,
            "options": options

        })

    return render(
        request,
        "train_engine/sentence_detail.html",
        {
            "sentence": sentence,
            "questions": data
        }
    )

# =========================
# 新增题目
# =========================
def question_create(request, sentence_id):

    from .models import Sentence, Question
    from django.shortcuts import redirect

    sentence = Sentence.objects.get(id=sentence_id)

    if request.method == "POST":

        qtype = request.POST.get("qtype", "").strip()
        question_text = request.POST.get("question", "").strip()
        answer = request.POST.get("answer", "").strip()
        pattern = request.POST.get("pattern", "").strip()
        blank_mode = request.POST.get("blank_mode", "auto").strip()
        is_multiple_choice = request.POST.get("is_multiple_choice") == "on"
        option_count = request.POST.get("option_count", "4").strip()
        manual_distractors = request.POST.get("manual_distractors", "").strip()

        if qtype:

            q = Question.objects.create(
                sentence=sentence,
                qtype=qtype,
                question=question_text or None,
                answer=answer or None,
                pattern=pattern or None,
                blank_mode=blank_mode or "auto",
                is_multiple_choice=is_multiple_choice,
                option_count=int(option_count) if option_count.isdigit() else 4,
                manual_distractors=manual_distractors or None
            )

            # 再保存一次，触发自动同步逻辑
            q.save()
            
            # 如果是选择题，保存选项
            if q.qtype == "choice":

                from .models import ChoiceOption

                # 删除旧选项
                q.options.all().delete()

                option_texts = request.POST.getlist("option_text")
                correct_flags = request.POST.getlist("correct_option")

                for i, text in enumerate(option_texts):

                    text = text.strip()

                    if not text:
                        continue

                    is_correct = str(i) in correct_flags

                    ChoiceOption.objects.create(
                        question=q,
                        text=text,
                        is_correct=is_correct,
                        is_auto_generated=False,
                        order=i
                    )

            return redirect(f"/sentence/{sentence_id}/")

    return render(
        request,
        "train_engine/question_form.html",
        {
            "mode": "create",
            "sentence": sentence,
            "question_obj": None
        }
    )


# =========================
# 编辑题目
# =========================
def question_edit(request, question_id):

    from .models import Question
    from django.shortcuts import redirect

    q = Question.objects.get(id=question_id)
    sentence = q.sentence

    if request.method == "POST":

        qtype = request.POST.get("qtype", "").strip()
        question_text = request.POST.get("question", "").strip()
        answer = request.POST.get("answer", "").strip()
        pattern = request.POST.get("pattern", "").strip()
        blank_mode = request.POST.get("blank_mode", "auto").strip()
        is_multiple_choice = request.POST.get("is_multiple_choice") == "on"
        option_count = request.POST.get("option_count", "4").strip()
        manual_distractors = request.POST.get("manual_distractors", "").strip()

        q.qtype = qtype or q.qtype
        q.question = question_text or None
        q.answer = answer or None
        q.pattern = pattern or None
        q.blank_mode = blank_mode or "auto"
        q.is_multiple_choice = is_multiple_choice
        q.option_count = int(option_count) if option_count.isdigit() else 4
        q.manual_distractors = manual_distractors or None

        # 保存时自动同步题目内容 / 选项
        q.save()

        # 如果是选择题，更新选项
        if q.qtype == "choice":

            from .models import ChoiceOption

            q.options.all().delete()

            option_texts = request.POST.getlist("option_text")
            correct_flags = request.POST.getlist("correct_option")

            for i, text in enumerate(option_texts):

                text = text.strip()

                if not text:
                    continue

                is_correct = str(i) in correct_flags

                ChoiceOption.objects.create(
                    question=q,
                    text=text,
                    is_correct=is_correct,
                    is_auto_generated=False,
                    order=i
                )

        return redirect(f"/sentence/{sentence.id}/")

    return render(
        request,
        "train_engine/question_form.html",
        {
            "mode": "edit",
            "sentence": sentence,
            "question_obj": q
        }
    )


# =========================
# 删除题目
# =========================
def question_delete(request, question_id):

    from .models import Question
    from django.shortcuts import redirect

    q = Question.objects.get(id=question_id)
    sentence_id = q.sentence.id

    q.delete()

    return redirect(f"/sentence/{sentence_id}/")

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
# Speaking：音频转写（Whisper）
# =========================
@csrf_exempt
@require_POST
def transcribe_speaking_audio(request):

    import os
    import tempfile
    from openai import OpenAI

    try:
        audio_file = request.FILES.get("audio")

        if not audio_file:
            return JsonResponse({"error": "audio missing"}, status=400)

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return JsonResponse({"error": "OPENAI_API_KEY not set"}, status=500)

        suffix = ".webm"
        original_name = getattr(audio_file, "name", "") or ""

        if "." in original_name:
            suffix = "." + original_name.split(".")[-1].lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        client = OpenAI(api_key=api_key)

        with open(temp_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )

        try:
            os.remove(temp_path)
        except Exception:
            pass

        text = getattr(transcript, "text", "") or ""

        return JsonResponse({
            "text": text
        })

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)



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