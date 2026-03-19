from django.shortcuts import render
from ..models import Book


def dashboard(request):
    """
    首页：书册列表
    """

    books = Book.objects.filter(owner=request.user) if request.user.is_authenticated else []

    return render(request, "train/dashboard.html", {
        "books": books
    })