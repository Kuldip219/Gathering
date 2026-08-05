from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Post, Like
from .forms import PostForm

User = get_user_model()


@login_required
def home_feed(request):
    family_members = User.objects.exclude(pk=request.user.pk)
    # prefetch_related('likes') + template's `|length` filter (not `.count`)
    # avoids an extra query per post when counting likes.
    posts = Post.objects.select_related('author').prefetch_related('likes')
    liked_post_ids = set(
        Like.objects.filter(user=request.user).values_list('post_id', flat=True)
    )

    context = {
        'family_members': family_members,
        'posts': posts,
        'liked_post_ids': liked_post_ids,
    }
    return render(request, 'posts/home.html', context)


@login_required
def create_post(request):
    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, "Post shared.")
            return redirect('home')
    else:
        form = PostForm()

    return render(request, 'posts/create_post.html', {'form': form})


@login_required
def toggle_like(request, post_id):
    if request.method != 'POST':
        return redirect('home')

    post = get_object_or_404(Post, pk=post_id)
    like, created = Like.objects.get_or_create(user=request.user, post=post)
    if not created:
        like.delete()  # already liked -> this click means "unlike"

    next_url = request.POST.get('next')
    if not (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})):
        next_url = 'home'
    return redirect(next_url)
