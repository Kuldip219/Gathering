from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import User
from .forms import ProfileEditForm

# Create your views here.
@login_required
def edit_profile(request):
    return redirect('profile', username=request.user.username)

@login_required
def profile_redirect(request):
    profile_user = get_object_or_404(User, username=username)
    is_own_profile = profile_user == request.user

    form = None
    if is_own_profile:
        if request.method == 'POST':
            form = ProfileEditForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('profile', username=profile_user.username)
        else:
            form = ProfileEditForm(instance=profile_user)
    
    context = {
        'profile_user': profile_user,
        'is_own_profile': is_own_profile,
        'form': form,
    }
    return render(request, 'accounts/profile.html', context)