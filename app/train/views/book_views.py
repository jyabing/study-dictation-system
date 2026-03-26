from django.shortcuts import render, get_object_or_404, redirect
from ..models import Book, Lesson
from .train_views import (
    get_today_plan,
    get_stats,
    get_dashboard_cycle_summary,
    get_book_lessons_cycle_summary,
    get_dashboard_books_cycle_summary,
)
from django.contrib.auth.decorators import login_required

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

    return render(request, "train/dashboard.html", {
        "books": books,
        "plan": plan,
        "stats": stats,
        "cycle_summary": cycle_summary,
        "book_cycle_summary": book_cycle_summary,
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