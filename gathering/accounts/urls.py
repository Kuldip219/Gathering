from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from . import views
from .forms import LoginForm

urlpatterns = [
    path(
        'login/',
        LoginView.as_view(template_name='accounts/login.html', authentication_form=LoginForm),
        name='login',
    ),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', views.profile_redirect, name='profile_redirect'),
    path('profile/<str:username>/', views.profile_view, name='profile'),
    path('signup/', views.signup_view, name='signup'),
]