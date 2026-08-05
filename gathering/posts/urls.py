from django.urls import path

from . import views

urlpatterns = [
    path('', views.home_feed, name='home'),
    path('post/create/', views.create_post, name='create_post'),
    path('post/<int:post_id>/like/', views.toggle_like, name='toggle_like'),
]
