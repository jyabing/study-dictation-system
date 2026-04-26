from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from ..models import Book, Lesson, Question, QuestionMemory
from .train_views import (
    get_book_lessons_cycle_summary,
    get_dashboard_books_cycle_summary,
    get_today_plan,
    _get_scope_plan_items,
    _build_scope_plan_stats,
)
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

@login_required
def book_create(request):

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()

        if title:
            book = Book.objects.create(
                owner=request.user,
                title=title,
                description=description
            )
            return redirect("book-detail", book_id=book.id)

    return render(request, "train/book_create.html", {
        "page_title": "添加书册",
    })

@login_required
def dashboard(request):

    # =========================
    # 新建自己的书册
    # =========================
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()

        if title:
            Book.objects.create(
                owner=request.user,
                title=title,
                description=description
            )
            return redirect("dashboard")

    books = list(Book.objects.filter(owner=request.user).order_by("-id"))
    raw_book_cycle_summary = get_dashboard_books_cycle_summary(request.user, books)

    book_cycle_summary = []
    for item in raw_book_cycle_summary:
        if not isinstance(item, dict):
            book_cycle_summary.append(item)
            continue

        row = dict(item)
        book_obj = row.get("book")

        if book_obj:
            row["id"] = row.get("id") or getattr(book_obj, "id", None)
            row["book_id"] = row.get("book_id") or getattr(book_obj, "id", None)
            row["title"] = row.get("title") or getattr(book_obj, "title", "")
            row["description"] = row.get("description") or getattr(book_obj, "description", "")
        else:
            row["id"] = row.get("id") or row.get("book_id")
            row["book_id"] = row.get("book_id") or row.get("id")
            row["title"] = row.get("title") or ""
            row["description"] = row.get("description") or ""

        row["pending_count"] = row.get(
            "pending_count",
            row.get("due_now_count", row.get("today_due_count", 0))
        )
        row["in_progress_count"] = row.get("in_progress_count", row.get("short_count", 0))
        row["mastered_count"] = row.get("mastered_count", row.get("long_count", 0))

        row["current_stage"] = row.get("current_stage") or row.get("main_stage") or "暂无阶段信息"
        row["current_stage_label"] = row.get("current_stage_label") or row["current_stage"]
        row["next_review_display"] = row.get("next_review_display") or row.get("next_review_text") or "未安排"

        focus_lesson_id = None

        if row.get("book_id"):
            focus_memory = (
                QuestionMemory.objects
                .filter(
                    user=request.user,
                    question__lesson__book_id=row["book_id"],
                )
                .select_related("question__lesson")
                .order_by("next_review_at", "question__lesson__id", "question__id")
                .first()
            )

            if focus_memory and getattr(focus_memory, "question", None):
                focus_lesson_id = getattr(focus_memory.question, "lesson_id", None)

        row["focus_lesson_id"] = focus_lesson_id

        overdue_count = row.get("overdue_count") or 0
        due_now_count = row.get("due_now_count", row.get("today_due_count", 0)) or 0
        new_count = row.get("new_count") or 0

        row["today_due_count"] = due_now_count
        row["due_now_count"] = due_now_count
        row["today_actionable_count"] = overdue_count + due_now_count + new_count
        row["is_today_actionable"] = row["today_actionable_count"] > 0

        if overdue_count > 0:
            row["priority_status"] = "overdue"
            row["priority_status_label"] = "逾期待复习"
        elif due_now_count > 0:
            row["priority_status"] = "due_today"
            row["priority_status_label"] = "当前到期"
        elif new_count > 0:
            row["priority_status"] = "new_available"
            row["priority_status_label"] = "可开始新学"
        else:
            row["priority_status"] = "idle"
            row["priority_status_label"] = "今日无任务"

        book_cycle_summary.append(row)

    def _priority_sort_key(x):
        overdue_count = x.get("overdue_count") or 0
        due_now_count = x.get("due_now_count", x.get("today_due_count", 0)) or 0
        pending_count = x.get("pending_count") or 0
        new_count = x.get("new_count") or 0

        next_review_text = x.get("next_review_text") or ""
        next_review_missing = 1 if next_review_text in {"", "未安排", "待安排"} else 0

        priority_rank = (
            0 if overdue_count > 0
            else 1 if due_now_count > 0
            else 2 if new_count > 0
            else 9
        )

        return (
            priority_rank,
            -overdue_count,
            -due_now_count,
            -pending_count,
            next_review_missing,
            next_review_text,
            x.get("id") or x.get("book_id") or 0,
        )

    actionable_books = [
        row for row in book_cycle_summary
        if row.get("is_today_actionable")
    ]

    priority_books = sorted(
        actionable_books,
        key=_priority_sort_key
    )[:5]

    dashboard_has_priority_books = len(priority_books) > 0

    dashboard_plan = get_today_plan(request)

    dashboard_due_items = _get_scope_plan_items(
        dashboard_plan["items"],
        "global_due",
        request.user
    )

    dashboard_overdue_items = _get_scope_plan_items(
        dashboard_plan["items"],
        "global_overdue",
        request.user
    )

    dashboard_due_stats = _build_scope_plan_stats(
        request,
        dashboard_due_items
    )

    dashboard_overdue_stats = _build_scope_plan_stats(
        request,
        dashboard_overdue_items
    )

    today_due_total = max(
        0,
        dashboard_due_stats["total"] - dashboard_due_stats["done"]
    )

    today_overdue_total = max(
        0,
        dashboard_overdue_stats["total"] - dashboard_overdue_stats["done"]
    )

    completed_total = sum(
        (row.get("mastered_count") or 0)
        for row in book_cycle_summary
    )

    return render(request, "train/dashboard.html", {
        "books": books,
        "all_books": book_cycle_summary,
        "priority_books": priority_books,
        "today_due_total": today_due_total,
        "today_overdue_total": today_overdue_total,
        "completed_total": completed_total,
        "dashboard_has_priority_books": dashboard_has_priority_books,
    })

# =========================
# Active Training Books
# =========================
@login_required
def active_training_books(request):

    books = list(Book.objects.filter(owner=request.user).order_by("-id"))
    raw_book_cycle_summary = get_dashboard_books_cycle_summary(request.user, books)

    book_cycle_summary = []
    for item in raw_book_cycle_summary:
        if not isinstance(item, dict):
            book_cycle_summary.append(item)
            continue

        row = dict(item)
        book_obj = row.get("book")

        if book_obj:
            row["id"] = row.get("id") or getattr(book_obj, "id", None)
            row["book_id"] = row.get("book_id") or getattr(book_obj, "id", None)
            row["title"] = row.get("title") or getattr(book_obj, "title", "")
            row["description"] = row.get("description") or getattr(book_obj, "description", "")
        else:
            row["id"] = row.get("id") or row.get("book_id")
            row["book_id"] = row.get("book_id") or row.get("id")
            row["title"] = row.get("title") or ""
            row["description"] = row.get("description") or ""

        row["pending_count"] = row.get(
            "pending_count",
            row.get("due_now_count", row.get("today_due_count", 0))
        )
        row["in_progress_count"] = row.get("in_progress_count", row.get("short_count", 0))
        row["mastered_count"] = row.get("mastered_count", row.get("long_count", 0))

        row["current_stage"] = row.get("current_stage") or row.get("main_stage") or "暂无阶段信息"
        row["current_stage_label"] = row.get("current_stage_label") or row["current_stage"]
        row["next_review_display"] = row.get("next_review_display") or row.get("next_review_text") or "未安排"

        focus_lesson_id = None

        if row.get("book_id"):
            focus_memory = (
                QuestionMemory.objects
                .filter(
                    user=request.user,
                    question__lesson__book_id=row["book_id"],
                )
                .select_related("question__lesson")
                .order_by("next_review_at", "question__lesson__id", "question__id")
                .first()
            )

            if focus_memory and getattr(focus_memory, "question", None):
                focus_lesson_id = getattr(focus_memory.question, "lesson_id", None)

        row["focus_lesson_id"] = focus_lesson_id

        overdue_count = row.get("overdue_count") or 0
        due_now_count = row.get("due_now_count", row.get("today_due_count", 0)) or 0
        new_count = row.get("new_count") or 0

        row["today_due_count"] = due_now_count
        row["due_now_count"] = due_now_count
        row["today_actionable_count"] = overdue_count + due_now_count + new_count
        row["is_today_actionable"] = row["today_actionable_count"] > 0

        if overdue_count > 0:
            row["priority_status"] = "overdue"
            row["priority_status_label"] = "逾期待复习"
        elif due_now_count > 0:
            row["priority_status"] = "due_today"
            row["priority_status_label"] = "当前到期"
        elif new_count > 0:
            row["priority_status"] = "new_available"
            row["priority_status_label"] = "可开始新学"
        else:
            row["priority_status"] = "idle"
            row["priority_status_label"] = "今日无任务"

        book_cycle_summary.append(row)

    def _priority_sort_key(x):
        overdue_count = x.get("overdue_count") or 0
        due_now_count = x.get("due_now_count", x.get("today_due_count", 0)) or 0
        pending_count = x.get("pending_count") or 0
        new_count = x.get("new_count") or 0

        next_review_text = x.get("next_review_text") or ""
        next_review_missing = 1 if next_review_text in {"", "未安排", "待安排"} else 0

        priority_rank = (
            0 if overdue_count > 0
            else 1 if due_now_count > 0
            else 2 if new_count > 0
            else 9
        )

        return (
            priority_rank,
            -overdue_count,
            -due_now_count,
            -pending_count,
            next_review_missing,
            next_review_text,
            x.get("id") or x.get("book_id") or 0,
        )

    active_books = [
        row for row in book_cycle_summary
        if row.get("is_today_actionable")
    ]

    active_books = sorted(
        active_books,
        key=_priority_sort_key
    )

    active_books_total = len(active_books)

    dashboard_plan = get_today_plan(request)

    dashboard_due_items = _get_scope_plan_items(
        dashboard_plan["items"],
        "global_due",
        request.user
    )

    dashboard_overdue_items = _get_scope_plan_items(
        dashboard_plan["items"],
        "global_overdue",
        request.user
    )

    dashboard_due_stats = _build_scope_plan_stats(
        request,
        dashboard_due_items
    )

    dashboard_overdue_stats = _build_scope_plan_stats(
        request,
        dashboard_overdue_items
    )

    today_due_total = max(
        0,
        dashboard_due_stats["total"] - dashboard_due_stats["done"]
    )

    today_overdue_total = max(
        0,
        dashboard_overdue_stats["total"] - dashboard_overdue_stats["done"]
    )

    return render(request, "train/active_training_books.html", {
        "active_books": active_books,
        "active_books_total": active_books_total,
        "today_due_total": today_due_total,
        "today_overdue_total": today_overdue_total,
    })

# =========================
# Book Detail
# =========================
@login_required
def book_detail(request, book_id):

    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    # =========================
    # 在当前书册下新增 lesson
    # =========================
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()

        try:
            order = int(request.POST.get("order") or 0)
        except ValueError:
            order = 0

        if title:
            Lesson.objects.create(
                book=book,
                title=title,
                order=order
            )
            return redirect("book-detail", book_id=book.id)

    lessons = Lesson.objects.filter(book=book).order_by("order", "id")
    lesson_cycle_summary = get_book_lessons_cycle_summary(request.user, book)

    lesson_summary_map = {}

    for row in lesson_cycle_summary:
        lesson_obj = row.get("lesson")
        lesson_id = getattr(lesson_obj, "id", None)

        if lesson_id is not None:
            lesson_summary_map[lesson_id] = row

    lessons = list(lessons)

    for lesson in lessons:
        row = lesson_summary_map.get(lesson.id, {})

        lesson.new_count = row.get("new_count", 0)
        lesson.short_count = row.get("short_count", 0)
        lesson.long_count = row.get("long_count", 0)

        lesson.in_progress_count = row.get("short_count", 0)
        lesson.mastered_count = row.get("long_count", 0)

        lesson.due_now_count = row.get("due_now_count", 0)
        lesson.later_today_count = row.get("later_today_count", 0)
        lesson.future_count = row.get("future_count", 0)

        lesson.today_due_count = row.get("today_due_count", 0)
        lesson.due_count = row.get("today_due_count", 0)
        lesson.overdue_count = row.get("overdue_count", 0)

        lesson.next_review_text = row.get("next_review_text", "未安排")
        lesson.current_stage = row.get("main_stage", "尚未开始")
        lesson.current_stage_label = row.get("main_stage", "尚未开始")

        lesson.priority_status = row.get("priority_status", "idle")
        lesson.priority_status_label = row.get("priority_status_label", "暂无安排")
        lesson.risk_level = row.get("risk_level", "稳定")

    book_cycle_summary_list = get_dashboard_books_cycle_summary(request.user, [book])
    book_cycle_summary = book_cycle_summary_list[0] if book_cycle_summary_list else {
        "book": book,
        "new_count": 0,
        "short_count": 0,
        "long_count": 0,
        "today_due_count": 0,
        "overdue_count": 0,
        "main_stage": "尚未开始",
        "next_review_text": "待安排",
        "risk_level": "稳定",
    }

    return render(request, "train/book_detail.html", {
        "book": book,
        "lessons": lessons,
        "lesson_cycle_summary": lesson_cycle_summary,
        "book_cycle_summary": book_cycle_summary,
        "head_actions": [
            {"label": "返回首页", "url": reverse("dashboard")},
            {"label": "编辑书册", "url": reverse("book-edit", args=[book.id])},
        ],
        "head_meta": [
            {"label": "书册：", "text": book.title},
            {"label": "章节数：", "text": str(len(lessons))},
        ],
        "head_chips": [
            {"kind": "primary", "text": f"今日到期：{book_cycle_summary.get('today_due_count', 0)}"},
            {"kind": "warning", "text": f"逾期：{book_cycle_summary.get('overdue_count', 0)}"},
            {"kind": "primary", "text": f"主阶段：{book_cycle_summary.get('main_stage', '尚未开始')}"},
        ],
    })

@login_required
def book_edit(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    next_url = request.GET.get("next") or request.POST.get("next") or "/"

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()

        if title:
            book.title = title
            book.description = description
            book.save(update_fields=["title", "description"])
            return redirect(next_url)

    return render(request, "train/edit_item.html", {
        "mode": "book",
        "obj": book,
        "next": next_url,
        "page_title": "编辑书册",
    })


@login_required
def lesson_edit(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    next_url = request.GET.get("next") or request.POST.get("next") or f"/book/{lesson.book_id}/"

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()

        try:
            order = int(request.POST.get("order") or 0)
        except ValueError:
            order = 0

        if title:
            lesson.title = title
            lesson.order = order
            lesson.save(update_fields=["title", "order"])
            return redirect(next_url)

    return render(request, "train/edit_item.html", {
        "mode": "lesson",
        "obj": lesson,
        "next": next_url,
        "page_title": "编辑章节",
    })

@login_required
def book_delete_confirm(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    lesson_count = Lesson.objects.filter(book=book).count()
    question_count = Question.objects.filter(lesson__book=book).count()

    next_url = request.GET.get("next") or "/"

    return render(request, "train/book_delete_confirm.html", {
        "book": book,
        "lesson_count": lesson_count,
        "question_count": question_count,
        "next": next_url,
        "page_title": "删除书册",
    })


@login_required
@require_POST
def book_delete_submit(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    book.delete()
    return redirect("dashboard")


@login_required
def lesson_delete_confirm(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    question_count = Question.objects.filter(lesson=lesson).count()

    next_url = request.GET.get("next") or f"/book/{lesson.book_id}/"

    return render(request, "train/lesson_delete_confirm.html", {
        "lesson": lesson,
        "book": lesson.book,
        "question_count": question_count,
        "next": next_url,
        "page_title": "删除章节",
    })


@login_required
@require_POST
def lesson_delete_submit(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    book_id = lesson.book_id
    lesson.delete()

    return redirect("book-detail", book_id=book_id)