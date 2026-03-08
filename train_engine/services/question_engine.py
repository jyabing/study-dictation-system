import random
import re

from train_engine.models import ChoiceOption, Question


# =========================
# 工具：去掉标注后的纯文本
# 例：
# Ask me where you {live}.
# -> Ask me where you live.
# =========================
def strip_markup(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\{([^{}|]+)(\|[^{}]+)?\}", r"\1", text)


# =========================
# 工具：提取标注目标
# 例：
# Ask me where you {live|verb}.
# -> [{"word": "live", "tag": "verb"}]
# =========================
def extract_targets(text: str):
    targets = []
    if not text:
        return targets

    matches = re.findall(r"\{([^{}|]+)(?:\|([^{}]+))?\}", text)

    for word, tag in matches:
        targets.append({
            "word": word.strip(),
            "tag": (tag or "").strip()
        })

    return targets


# =========================
# 自动挖空：
# 1）如果 sentence 有 {} 标注，优先按标注挖
# 2）否则自动挑一个中间词挖空
# =========================
def build_cloze(sentence_text: str, blank_mode: str = "auto"):
    if not sentence_text:
        return "", ""

    clean_text = strip_markup(sentence_text)
    targets = extract_targets(sentence_text)

    # 指定挖空：使用 {} 标注
    if blank_mode == "specified" and targets:
        answer_parts = [t["word"] for t in targets]
        question = sentence_text

        for t in targets:
            raw1 = "{" + t["word"] + "}"
            raw2 = "{" + t["word"] + "|" + t["tag"] + "}" if t["tag"] else None
            question = question.replace(raw1, "_____")
            if raw2:
                question = question.replace(raw2, "_____")

        question = strip_markup(question)
        return question, " | ".join(answer_parts)

    # 自动模式：有标注时仍优先使用标注
    if blank_mode == "auto" and targets:
        answer_parts = [t["word"] for t in targets]
        question = sentence_text

        for t in targets:
            raw1 = "{" + t["word"] + "}"
            raw2 = "{" + t["word"] + "|" + t["tag"] + "}" if t["tag"] else None
            question = question.replace(raw1, "_____")
            if raw2:
                question = question.replace(raw2, "_____")

        question = strip_markup(question)
        return question, " | ".join(answer_parts)

    # 没标注时：自动找一个合适位置
    words = clean_text.split()
    if len(words) <= 2:
        return clean_text, clean_text

    idx = max(1, min(len(words) - 2, len(words) // 2))
    answer = words[idx]
    words[idx] = "_____"

    return " ".join(words), answer


# =========================
# 把 answer 拆成多选/单选答案列表
# 规则：每行一个正确项
# =========================
def parse_answer_lines(answer_text: str):
    if not answer_text:
        return []
    return [x.strip() for x in answer_text.splitlines() if x.strip()]


# =========================
# 把人工混淆项拆成列表
# 规则：每行一个
# =========================
def parse_manual_distractors(text: str):
    if not text:
        return []
    return [x.strip() for x in text.splitlines() if x.strip()]


# =========================
# 自动补齐混淆项
# 这里只做“安全的基础版本”
# 规则：
# - 优先同句中其它词
# - 再用通用池补齐
# =========================
def generate_auto_distractors(correct_items, sentence_text, needed_count):
    distractors = []

    # 1）优先从句子词中找
    sentence_words = [
        w.strip(".,!?;:()[]{}\"'")
        for w in strip_markup(sentence_text).split()
    ]
    sentence_words = [w for w in sentence_words if w]

    for w in sentence_words:
        if w not in correct_items and w not in distractors:
            distractors.append(w)
        if len(distractors) >= needed_count:
            return distractors[:needed_count]

    # 2）再从通用池补
    generic_pool = [
        "work", "study", "live", "stay",
        "Tokyo", "Kyoto", "Osaka", "Nagoya",
        "yes", "no", "always", "never",
        "happy", "busy", "tired", "ready",
    ]

    for w in generic_pool:
        if w not in correct_items and w not in distractors:
            distractors.append(w)
        if len(distractors) >= needed_count:
            return distractors[:needed_count]

    return distractors[:needed_count]


# =========================
# 选择题同步：
# - 正确项由 answer 提供（每行一个）
# - 手工混淆项由 manual_distractors 提供（每行一个）
# - 不够 option_count 时系统自动补齐
# - 每次保存 Question 时重建 ChoiceOption
# =========================
def rebuild_choice_options(question_obj: Question):
    correct_items = parse_answer_lines(question_obj.answer or "")
    manual_items = parse_manual_distractors(question_obj.manual_distractors or "")

    if not correct_items:
        return

    target_count = max(question_obj.option_count or 4, len(correct_items))

    auto_needed = target_count - len(correct_items) - len(manual_items)
    auto_needed = max(0, auto_needed)

    auto_items = generate_auto_distractors(
        correct_items=correct_items,
        sentence_text=question_obj.sentence.text,
        needed_count=auto_needed,
    )

    # 每次重建，避免旧数据残留
    question_obj.options.all().delete()

    # 正确项
    for item in correct_items:
        ChoiceOption.objects.create(
            question=question_obj,
            text=item,
            is_correct=True,
            is_auto_generated=False
        )

    # 手工混淆项
    for item in manual_items:
        if item not in correct_items:
            ChoiceOption.objects.create(
                question=question_obj,
                text=item,
                is_correct=False,
                is_auto_generated=False
            )

    # 系统补齐项
    for item in auto_items:
        if item not in correct_items and item not in manual_items:
            ChoiceOption.objects.create(
                question=question_obj,
                text=item,
                is_correct=False,
                is_auto_generated=True
            )


# =========================
# 核心：根据 Question 类型自动同步内容
# =========================
def sync_question_content(question_obj: Question):
    sentence_text = question_obj.sentence.text or ""

    # 挖空题：如果 question/answer 没填，就自动生成
    if question_obj.qtype == "cloze":
        if not question_obj.question or not question_obj.answer:
            q, a = build_cloze(sentence_text, blank_mode=question_obj.blank_mode)
            Question.objects.filter(pk=question_obj.pk).update(
                question=q,
                answer=a
            )

    # 听力题：默认整句听写
    elif question_obj.qtype == "listening":
        update_dict = {}
        if not question_obj.question:
            update_dict["question"] = strip_markup(sentence_text)
        if not question_obj.answer:
            update_dict["answer"] = strip_markup(sentence_text)

        if update_dict:
            Question.objects.filter(pk=question_obj.pk).update(**update_dict)

    # 朗读题：默认整句朗读
    elif question_obj.qtype == "speaking":
        update_dict = {}
        if not question_obj.question:
            update_dict["question"] = strip_markup(sentence_text)
        if not question_obj.answer:
            update_dict["answer"] = strip_markup(sentence_text)

        if update_dict:
            Question.objects.filter(pk=question_obj.pk).update(**update_dict)

    # 选择题：自动补齐选项
    elif question_obj.qtype == "choice":
        rebuild_choice_options(question_obj)

    # 问答题：不自动生成内容，只保留 pattern 提示
    elif question_obj.qtype == "qa":
        pass


# =========================
# 自动确保 Cloze Question 存在
# 用于后台或批量初始化
# =========================
def ensure_cloze_question(sentence):
    """
    确保某个 Sentence 至少有一个 Cloze Question
    如果没有就自动创建
    """

    q, created = Question.objects.get_or_create(
        sentence=sentence,
        qtype="cloze",
        defaults={
            "blank_mode": "auto",
            "is_auto_generated": True
        }
    )

    # 如果新创建，立即同步题目内容
    if created:
        sync_question_content(q)

    return q