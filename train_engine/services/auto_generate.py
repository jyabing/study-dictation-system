import random

from train_engine.models import Question, ChoiceOption


# =========================
# 自动挖空
# =========================
def generate_cloze(sentence):

    words = sentence.split()

    if len(words) < 3:
        return None

    idx = random.randint(1, len(words)-2)

    answer = words[idx]

    words[idx] = "_____"

    question = " ".join(words)

    return question, answer


# =========================
# 自动生成干扰项
# =========================
def generate_distractors(answer):

    common = [
        "Tokyo",
        "Kyoto",
        "Osaka",
        "Nagoya",
        "London",
        "Paris",
        "New York"
    ]

    distractors = []

    for w in common:
        if w.lower() != answer.lower():
            distractors.append(w)

    random.shuffle(distractors)

    return distractors[:3]


# =========================
# 自动生成题目
# =========================
def generate_questions(sentence_obj):

    text = sentence_obj.text

    # ======================
    # 1 问答题
    # ======================
    Question.objects.create(
        sentence=sentence_obj,
        qtype="qa",
        question=text,
        answer=text
    )

    # ======================
    # 2 听写
    # ======================
    Question.objects.create(
        sentence=sentence_obj,
        qtype="listening",
        question="Listen and type what you hear.",
        answer=text
    )

    # ======================
    # 3 朗读
    # ======================
    Question.objects.create(
        sentence=sentence_obj,
        qtype="speaking",
        question=text,
        answer=text
    )

    # ======================
    # 4 挖空
    # ======================
    cloze = generate_cloze(text)

    if cloze:

        q, a = cloze

        Question.objects.create(
            sentence=sentence_obj,
            qtype="cloze",
            question=q,
            answer=a
        )

    # ======================
    # 5 选择题
    # ======================
    answer = text.split()[-1].replace(".", "")

    q = Question.objects.create(
        sentence=sentence_obj,
        qtype="choice",
        question="Choose the correct answer",
        answer=answer
    )

    options = generate_distractors(answer)

    ChoiceOption.objects.create(
        question=q,
        text=answer,
        is_correct=True
    )

    for o in options:

        ChoiceOption.objects.create(
            question=q,
            text=o,
            is_correct=False
        )