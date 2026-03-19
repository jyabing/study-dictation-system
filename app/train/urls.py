from django.urls import path
from .views.book_views import dashboard

urlpatterns = [
    path("", dashboard, name="dashboard"),
]