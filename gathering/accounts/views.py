from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import User
from .forms import ProfileEditForm, SignupForm

# Create your views here.
@login_required
def profile_redirect(request):
    return redirect('profile', username=request.user.username)


@login_required
def profile_view(request, username):
    profile_user = get_object_or_404(User, username=username)
    is_own_profile = profile_user == request.user

    form = None
    if is_own_profile:
        if request.method == 'POST':
            form = ProfileEditForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated.")
                return redirect('profile', username=profile_user.username)
        else:
            form = ProfileEditForm(instance=profile_user)

    context = {
        'profile_user': profile_user,
        'is_own_profile': is_own_profile,
        'form': form,
    }
    return render(request, 'accounts/profile.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('profile_redirect')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Two backends are configured, so login() needs to be told which
            # one authenticated this user (the form saved a fresh account).
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('profile_redirect')
    else:
        form = SignupForm()

    return render(request, 'accounts/signup.html', {'form': form})
