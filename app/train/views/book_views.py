from django.shortcuts import render, get_object_or_404, redirect
from ..models import Book, Lesson, Question
from .train_views import (
    get_book_lessons_cycle_summary,
    get_dashboard_books_cycle_summary,

)
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

@login_required
@login_required
def dashboard(request):

    print("SESSION:", request.session.get("today_done_ids"))
    print("USER:", request.user)
    print("BOOK COUNT:", Book.objects.count())
    print("MY BOOKS:", Book.objects.filter(owner=request.user).count())

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

        row["pending_count"] = row.get("pending_count", row.get("today_due_count", 0))
        row["in_progress_count"] = row.get("in_progress_count", row.get("short_count", 0))
        row["mastered_count"] = row.get("mastered_count", row.get("long_count", 0))

        row["current_stage"] = row.get("current_stage") or row.get("main_stage") or "暂无阶段信息"
        row["current_stage_label"] = row.get("current_stage_label") or row["current_stage"]
        row["next_review_display"] = row.get("next_review_display") or row.get("next_review_text") or "未安排"

        book_cycle_summary.append(row)

    def _priority_sort_key(x):
        risk_rank = (
            0 if x.get("risk_level") == "高风险"
            else 1 if x.get("risk_level") == "中风险"
            else 2
        )

        overdue_count = x.get("overdue_count") or 0
        pending_count = x.get("pending_count") or 0
        today_due_count = x.get("today_due_count") or 0

        next_review_text = x.get("next_review_text") or ""
        next_review_missing = 1 if next_review_text in {"", "未安排", "待安排"} else 0

        return (
            risk_rank,
            -overdue_count,
            -pending_count,
            -today_due_count,
            next_review_missing,
            next_review_text,
            x.get("id") or x.get("book_id") or 0,
        )

    priority_books = sorted(
        book_cycle_summary,
        key=_priority_sort_key
    )[:5]

    return render(request, "train/dashboard.html", {
        "books": books,
        "all_books": book_cycle_summary,
        "priority_books": priority_books,
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