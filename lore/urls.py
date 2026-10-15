from django.urls import path

from . import views

app_name = "lore"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/", views.entry, name="entry"),
    path("<slug:slug>/review/", views.review, name="review"),
]
