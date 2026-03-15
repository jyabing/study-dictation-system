import re
from typing import List, Dict, Optional

from train_engine.models import Question


# =========================
# 基础工具
# =========================
QUESTION_TYPE_QA = "qa"
QUESTION_TYPE_CLOZE = "cloze"
QUESTION_TYPE_CHOICE = "choice"
QUESTION_TYPE_LISTENING = "listening"
QUESTION_TYPE_SPEAKING = "speaking"


AUTO_TAG_V3 = "[FZH_V3]"


def normalize_sentence(text: str) -> str:
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[。！？]$", "", text)
    return text


def strip_final_punctuation(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"[.!?]+$", "", text.strip())


def ensure_question_mark(text: str) -> str:
    text = strip_final_punctuation(text)
    if not text:
        return ""
    return text + "?"


def ensure_period(text: str) -> str:
    text = strip_final_punctuation(text)
    if not text:
        return ""
    return text + "."


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return text.split()


def lower(s: str) -> str:
    return (s or "").strip().lower()


def starts_with_any(text: str, prefixes: List[str]) -> bool:
    text = lower(text)
    return any(text.startswith(p) for p in prefixes)


def contains_any(text: str, needles: List[str]) -> bool:
    text = lower(text)
    return any(n in text for n in needles)


# =========================
# 主语映射
# I -> you
# my -> your
# am -> are
# =========================
SUBJECT_MAP = {
    "i": "you",
    "you": "I",
    "my": "your",
    "your": "my",
    "me": "you",
    "am": "are",
    "are": "am",
}

DO_SUBJECTS = {"i", "you", "we", "they"}
DOES_SUBJECTS = {"he", "she", "it"}


# =========================
# 基础解析
# 针对简单句：
# I live in Japan
# I study every day
# I work because ...
# I go to school
# =========================
def parse_simple_sentence(text: str) -> Optional[Dict]:
    text = normalize_sentence(text)
    text = strip_final_punctuation(text)

    words = tokenize(text)
    if len(words) < 2:
        return None

    subject = words[0]
    verb = words[1]
    rest_words = words[2:] if len(words) > 2 else []
    rest = " ".join(rest_words)

    return {
        "raw": text,
        "subject": subject,
        "verb": verb,
        "rest_words": rest_words,
        "rest": rest,
    }


def to_second_person_subject(subject: str) -> str:
    return SUBJECT_MAP.get(lower(subject), lower(subject))


def choose_aux_by_subject(subject: str) -> str:
    s = lower(subject)
    if s in DOES_SUBJECTS:
        return "does"
    return "do"


def base_form_verb(verb: str) -> str:
    """
    这里只做安全的基础版，不做复杂词形还原。
    因为你当前句库大概率是原形句。
    """
    v = lower(verb)

    irregular = {
        "is": "be",
        "are": "be",
        "am": "be",
        "was": "be",
        "were": "be",
        "has": "have",
        "does": "do",
    }
    if v in irregular:
        return irregular[v]

    if v.endswith("ies") and len(v) > 3:
        return v[:-3] + "y"

    if v.endswith("es") and len(v) > 2:
        return v[:-2]

    if v.endswith("s") and len(v) > 1:
        return v[:-1]

    return v


# =========================
# 问句类型判断
# =========================
def detect_question_type(parsed: Dict) -> str:
    rest = lower(parsed.get("rest", ""))

    if not rest:
        return "what"

    # where
    if starts_with_any(rest, ["in ", "at ", "from ", "to ", "into ", "on "]):
        # to school / to Tokyo / in Japan / at home
        return "where"

    # when
    if starts_with_any(rest, ["every ", "on ", "at ", "this ", "today", "tomorrow", "tonight"]):
        return "when"

    if contains_any(rest, ["every day", "every morning", "every night", "yesterday", "today", "tomorrow"]):
        return "when"

    # why
    if contains_any(rest, ["because ", "because"]):
        return "why"

    # how
    if contains_any(rest, ["carefully", "hard", "well", "slowly", "quickly"]):
        return "how"

    return "what"


# =========================
# 问句构造
# =========================
def build_wh_question(parsed: Dict, wh_type: str) -> str:
    subject = to_second_person_subject(parsed["subject"])
    verb = base_form_verb(parsed["verb"])
    aux = choose_aux_by_subject(subject)

    if wh_type == "where":
        return ensure_question_mark(f"Where {aux} {subject} {verb}")

    if wh_type == "when":
        return ensure_question_mark(f"When {aux} {subject} {verb}")

    if wh_type == "why":
        return ensure_question_mark(f"Why {aux} {subject} {verb}")

    if wh_type == "how":
        return ensure_question_mark(f"How {aux} {subject} {verb}")

    return ensure_question_mark(f"What {aux} {subject} {verb}")


def build_yesno_question(parsed: Dict) -> str:
    subject = to_second_person_subject(parsed["subject"])
    verb = base_form_verb(parsed["verb"])
    aux = choose_aux_by_subject(subject)
    rest = parsed["rest"]

    if rest:
        return ensure_question_mark(f"{aux.capitalize()} {subject} {verb} {rest}")
    return ensure_question_mark(f"{aux.capitalize()} {subject} {verb}")


# =========================
# 触发句构造
# =========================
def build_ask_trigger(question_text: str) -> str:
    q = strip_final_punctuation(question_text)
    q = re.sub(r"[?]+$", "", q).strip()

    # Where do you live -> Ask me where you live
    q = re.sub(r"^(Where|When|Why|How|What)\s+", "", q, flags=re.I)
    q = re.sub(r"^(do|does|did)\s+", "", q, flags=re.I)

    return f"Ask me {q}".strip()


def build_tell_trigger(answer_text: str) -> str:
    answer_text = strip_final_punctuation(answer_text)
    return f"Tell me {answer_text}".strip()


def build_repeat_trigger(answer_text: str) -> str:
    answer_text = strip_final_punctuation(answer_text)
    return f"Repeat: {answer_text}".strip()


def build_shadowing_trigger(answer_text: str) -> str:
    answer_text = strip_final_punctuation(answer_text)
    return f"Shadow: {answer_text}".strip()


# =========================
# 模板集合
# =========================
def build_bidirectional_templates(sentence_text: str) -> List[Dict]:
    """
    输出统一结构：
    {
        "qtype": "qa",
        "question": "...",
        "answer": "...",
        "pattern": "...",
        "tag": "...",
    }
    """
    text = ensure_period(normalize_sentence(sentence_text))
    parsed = parse_simple_sentence(text)

    if not parsed:
        return [
            {
                "qtype": QUESTION_TYPE_QA,
                "question": f"{AUTO_TAG_V3} Repeat:",
                "answer": strip_final_punctuation(text),
                "pattern": "repeat",
                "tag": "repeat_only",
            },
            {
                "qtype": QUESTION_TYPE_SPEAKING,
                "question": f"{AUTO_TAG_V3} Shadow:",
                "answer": strip_final_punctuation(text),
                "pattern": "shadowing",
                "tag": "shadowing",
            },
        ]

    wh_type = detect_question_type(parsed)
    wh_question = build_wh_question(parsed, wh_type)
    yesno_question = build_yesno_question(parsed)
    ask_trigger = build_ask_trigger(wh_question)
    tell_trigger = build_tell_trigger(strip_final_punctuation(text))
    repeat_trigger = f"{AUTO_TAG_V3} Repeat:"
    shadow_trigger = f"{AUTO_TAG_V3} Shadow:"
    answer_text = strip_final_punctuation(text)

    templates = [
        # Ask -> WH Question
        {
            "qtype": QUESTION_TYPE_QA,
            "question": f"{AUTO_TAG_V3} {ask_trigger}",
            "answer": strip_final_punctuation(wh_question),
            "pattern": "ask_to_question",
            "tag": "ask_wh",
        },

        # WH Question -> Statement
        {
            "qtype": QUESTION_TYPE_QA,
            "question": f"{AUTO_TAG_V3} {strip_final_punctuation(wh_question)}",
            "answer": answer_text,
            "pattern": "question_to_answer",
            "tag": "wh_to_answer",
        },

        # Tell -> Statement
        {
            "qtype": QUESTION_TYPE_QA,
            "question": f"{AUTO_TAG_V3} {tell_trigger}",
            "answer": answer_text,
            "pattern": "tell_to_statement",
            "tag": "tell_answer",
        },

        # Yes/No Question -> Statement
        {
            "qtype": QUESTION_TYPE_QA,
            "question": f"{AUTO_TAG_V3} {strip_final_punctuation(yesno_question)}",
            "answer": answer_text,
            "pattern": "yesno_to_answer",
            "tag": "yesno_answer",
        },

        # Repeat
        {
            "qtype": QUESTION_TYPE_QA,
            "question": repeat_trigger,
            "answer": answer_text,
            "pattern": "repeat",
            "tag": "repeat_only",
        },

        # Shadowing
        {
            "qtype": QUESTION_TYPE_SPEAKING,
            "question": shadow_trigger,
            "answer": answer_text,
            "pattern": "shadowing",
            "tag": "shadowing",
        },

        # Listening
        {
            "qtype": QUESTION_TYPE_LISTENING,
            "question": f"{AUTO_TAG_V3} Listen and type what you hear.",
            "answer": answer_text,
            "pattern": "dictation",
            "tag": "listening_dictation",
        },

        # Speaking
        {
            "qtype": QUESTION_TYPE_SPEAKING,
            "question": f"{AUTO_TAG_V3} Say: {answer_text}",
            "answer": answer_text,
            "pattern": "say_sentence",
            "tag": "speaking_sentence",
        },
    ]

    return templates


# =========================
# Question 写入工具
# =========================
def create_question(
    sentence_obj,
    qtype: str,
    question_text: str,
    answer_text: str,
    pattern: str = "",
    sort_order: int = 0,
    blank_mode: str = "auto",
    is_auto_generated: bool = True,
):
    return Question.objects.create(
        sentence=sentence_obj,
        qtype=qtype,
        question=question_text,
        answer=answer_text,
        pattern=pattern or None,
        blank_mode=blank_mode,
        is_auto_generated=is_auto_generated,
        sort_order=sort_order,
    )


def is_v3_generated_question(q: Question) -> bool:
    return bool(q.is_auto_generated and q.question and q.question.startswith(AUTO_TAG_V3))


# =========================
# 仅生成 QA / speaking / listening
# 不覆盖人工修改题
# =========================
def create_fuzhonghan_v3_questions(sentence_obj) -> List[Question]:
    templates = build_bidirectional_templates(sentence_obj.text)
    created = []

    base_order = 100

    for i, item in enumerate(templates, start=1):
        q = create_question(
            sentence_obj=sentence_obj,
            qtype=item["qtype"],
            question_text=item["question"],
            answer_text=item["answer"],
            pattern=item["pattern"],
            sort_order=base_order + i,
            is_auto_generated=True,
        )
        created.append(q)

    return created


def ensure_fuzhonghan_v3_questions(sentence_obj) -> List[Question]:
    existing = Question.objects.filter(sentence=sentence_obj, is_auto_generated=True)

    # 已有 v3 自动题则不重复创建
    if any(is_v3_generated_question(q) for q in existing):
        return list(existing)

    return create_fuzhonghan_v3_questions(sentence_obj)


# =========================
# 删除旧 v3 自动题
# 不删人工编辑题
# =========================
def delete_fuzhonghan_v3_auto_questions(sentence_obj):
    qs = Question.objects.filter(sentence=sentence_obj, is_auto_generated=True)
    for q in qs:
        if is_v3_generated_question(q):
            q.delete()


# =========================
# 重建 v3 自动题
# 只删除 v3 自动生成题
# 人工修改题不动
# =========================
def rebuild_fuzhonghan_v3_questions(sentence_obj) -> List[Question]:
    delete_fuzhonghan_v3_auto_questions(sentence_obj)
    return create_fuzhonghan_v3_questions(sentence_obj)


# =========================
# 对外统一入口
# mode:
# ensure  -> 有就不重复建
# rebuild -> 重建 v3 自动题
# =========================
def generate_fuzhonghan_v3(sentence_obj, mode: str = "ensure") -> List[Question]:
    if mode == "rebuild":
        return rebuild_fuzhonghan_v3_questions(sentence_obj)
    return ensure_fuzhonghan_v3_questions(sentence_obj)