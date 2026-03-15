import random
import re

from ..models import Question, ChoiceOption


# =========================
# 去除标注
# {word} -> word
# =========================
def strip_markup(text: str):

    if not text:
        return ""

    return re.sub(r"\{([^{}|]+)(\|[^{}]+)?\}", r"\1", text)


# =========================
# 提取标注
# {live|verb}
# =========================
def extract_targets(text: str):

    targets = []

    matches = re.findall(r"\{([^{}|]+)(?:\|([^{}]+))?\}", text)

    for word, tag in matches:

        targets.append({
            "word": word.strip(),
            "tag": (tag or "").strip()
        })

    return targets


# =========================
# Cloze 题
# =========================
def build_cloze(sentence, level=1):

    text = sentence.text

    clean = strip_markup(text)

    targets = extract_targets(text)

    # 如果有标注，优先使用标注
    if targets:

        answers = []

        q = text

        for t in targets:

            answers.append(t["word"])

            raw1 = "{" + t["word"] + "}"
            raw2 = "{" + t["word"] + "|" + t["tag"] + "}"

            q = q.replace(raw1, "_____")
            q = q.replace(raw2, "_____")

        q = strip_markup(q)

        return q, " | ".join(answers)

    words = clean.split()

    if len(words) <= 2:
        return clean, clean

    blank_count = min(level, len(words))

    indexes = random.sample(range(len(words)), blank_count)

    answers = []

    for i in indexes:

        answers.append(words[i])

        words[i] = "_____"

    return " ".join(words), " | ".join(answers)


# =========================
# 生成干扰项
# =========================
def generate_distractors(correct, sentence_text, count):

    distractors = []

    words = strip_markup(sentence_text).split()

    words = [w.strip(".,!?") for w in words]

    for w in words:

        if w != correct and w not in distractors:

            distractors.append(w)

        if len(distractors) >= count:

            return distractors[:count]

    generic = [
        "work",
        "study",
        "live",
        "stay",
        "go",
        "come",
        "Japan",
        "Tokyo",
        "Kyoto",
        "Osaka",
        "yes",
        "no",
        "always",
        "never"
    ]

    for g in generic:

        if g != correct and g not in distractors:

            distractors.append(g)

        if len(distractors) >= count:

            return distractors[:count]

    return distractors[:count]


# =========================
# 生成选择题
# =========================
def build_choice(question):

    correct = (question.answer or "").strip()

    if not correct:

        return

    sentence_text = question.sentence.text

    option_count = question.option_count or 4

    distractors = generate_distractors(
        correct,
        sentence_text,
        option_count - 1
    )

    options = [correct] + distractors

    random.shuffle(options)

    question.options.all().delete()

    letters = ["A", "B", "C", "D", "E"]

    for i, text in enumerate(options):

        ChoiceOption.objects.create(

            question=question,

            letter=letters[i] if i < len(letters) else "",

            text=text,

            is_correct=(text == correct),

            order=i
        )


# =========================
# QA 问答题
# =========================
def build_qa(sentence):

    text = strip_markup(sentence.text)

    words = text.split()

    if len(words) < 3:

        return "Repeat:", text

    if words[0].lower() == "i":

        q = "Where do you " + " ".join(words[1:]) + "?"

        return q, text

    return "Repeat:", text


# =========================
# Listening
# =========================
def build_listening(sentence):

    text = strip_markup(sentence.text)

    return text, text


# =========================
# Speaking
# =========================
def build_speaking(sentence):

    text = strip_markup(sentence.text)

    return text, text


# =========================
# 同步 Question 内容
# =========================
def sync_question_content(question):

    sentence = question.sentence

    if question.qtype == "cloze":

        q, a = build_cloze(sentence)

        Question.objects.filter(id=question.id).update(
            question=q,
            answer=a
        )

    elif question.qtype == "choice":

        if not question.question:

            Question.objects.filter(id=question.id).update(
                question=strip_markup(sentence.text)
            )

        if question.answer:

            build_choice(question)

    elif question.qtype == "listening":

        q, a = build_listening(sentence)

        Question.objects.filter(id=question.id).update(
            question=q,
            answer=a
        )

    elif question.qtype == "speaking":

        q, a = build_speaking(sentence)

        Question.objects.filter(id=question.id).update(
            question=q,
            answer=a
        )

    elif question.qtype == "qa":

        q, a = build_qa(sentence)

        Question.objects.filter(id=question.id).update(
            question=q,
            answer=a
        )


# =========================
# 自动生成全部题型
# =========================
def generate_all_questions(sentence):

    qtypes = [
        "cloze",
        "choice",
        "listening",
        "speaking",
        "qa"
    ]

    questions = []

    for qt in qtypes:

        q, created = Question.objects.get_or_create(

            sentence=sentence,

            qtype=qt,

            defaults={
                "is_auto_generated": True
            }
        )

        if created:

            sync_question_content(q)

        questions.append(q)

    return questions