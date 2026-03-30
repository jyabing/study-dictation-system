from django.shortcuts import render, get_object_or_404, redirect
from ..models import Book, Lesson, Question
from .train_views import (
    get_today_plan,
    get_stats,
    get_dashboard_cycle_summary,
    get_book_lessons_cycle_summary,
    get_dashboard_books_cycle_summary,

)
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

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

    plan = get_today_plan(request)
    stats = get_stats(request)
    cycle_summary = get_dashboard_cycle_summary(request.user)
    book_cycle_summary = get_dashboard_books_cycle_summary(request.user, books)

    print("🔥 DEBUG plan =", plan)

    priority_books = sorted(
        book_cycle_summary,
        key=lambda x: (
            0 if x.get("risk_level") == "高风险" else 1 if x.get("risk_level") == "中风险" else 2,
            -(x.get("overdue_count") or 0),
            -(x.get("today_due_count") or 0),
            x.get("book").id if x.get("book") else 0,
        )
    )[:5]

    all_books_count = len(book_cycle_summary)

    return render(request, "train/dashboard.html", {
        "books": books,
        "plan": plan,
        "stats": stats,
        "cycle_summary": cycle_summary,
        "book_cycle_summary": book_cycle_summary,
        "priority_books": priority_books,
        "all_books_count": all_books_count,
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