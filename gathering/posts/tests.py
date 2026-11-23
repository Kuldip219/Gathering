"""Tests for posts: the feed, post creation, like toggling and the
open-redirect guard on the like endpoint."""

import os
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gathering.testing import (
    TemporaryMediaRootMixin,
    make_oversized_test_image,
    make_test_image,
    make_text_upload,
)

from .models import Like, Post

User = get_user_model()

PASSWORD = 'Str0ngPassw0rd!'


class FeedTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.bob = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )
        self.carol = User.objects.create_user(
            email='carol@example.com', username='carol', password=PASSWORD
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse('home'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('home')}")

    def test_posts_are_listed_newest_first(self):
        base = timezone.now()
        for index, caption in enumerate(['oldest', 'middle', 'newest']):
            post = Post.objects.create(author=self.bob, caption=caption)
            Post.objects.filter(pk=post.pk).update(
                created_at=base - timedelta(minutes=10 - index)
            )

        self.client.force_login(self.alice)
        response = self.client.get(reverse('home'))

        captions = [post.caption for post in response.context['posts']]
        self.assertEqual(captions, ['newest', 'middle', 'oldest'])

    def test_avatar_row_excludes_the_current_user(self):
        Post.objects.create(author=self.bob, caption='from bob')

        self.client.force_login(self.alice)
        response = self.client.get(reverse('home'))

        family_members = list(response.context['family_members'])
        self.assertNotIn(self.alice, family_members)
        self.assertEqual(
            sorted(member.username for member in family_members), ['bob', 'carol']
        )


class CreatePostTests(TemporaryMediaRootMixin, TestCase):
    # NOTE: files travel inside the `data` dict - the test client's third
    # positional argument is content_type, not a files mapping.
    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.create_url = reverse('create_post')

    def test_login_required(self):
        response = self.client.get(self.create_url)

        self.assertRedirects(
            response, f"{reverse('login')}?next={self.create_url}"
        )

    def test_caption_only_post_is_valid(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.create_url, {'caption': 'Just a caption'})

        self.assertRedirects(response, reverse('home'))
        post = Post.objects.get()
        self.assertEqual(post.caption, 'Just a caption')
        self.assertFalse(post.image)

    def test_image_only_post_is_valid(self):
        self.client.force_login(self.alice)

        response = self.client.post(
            self.create_url, {'caption': '', 'image': make_test_image('only.png')}
        )

        self.assertRedirects(response, reverse('home'))
        post = Post.objects.get()
        self.assertEqual(post.author, self.alice)
        self.assertTrue(post.image.name.startswith('posts/images/'))
        self.assertTrue(os.path.exists(post.image.path))

    def test_empty_post_is_rejected(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.create_url, {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertTrue(response.context['form'].non_field_errors())

    def test_author_is_the_logged_in_user(self):
        self.client.force_login(self.alice)

        self.client.post(self.create_url, {'caption': 'Mine'})

        self.assertEqual(Post.objects.get().author, self.alice)


class ToggleLikeTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.bob = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )
        self.post = Post.objects.create(author=self.bob, caption='Like me')
        self.like_url = reverse('toggle_like', kwargs={'post_id': self.post.pk})

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.like_url)

        self.assertRedirects(
            response, f"{reverse('login')}?next={self.like_url}"
        )

    def test_get_does_not_create_a_like(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.like_url)

        # The view sends non-POST requests back to the feed rather than
        # returning 405; either way a GET must never mutate state.
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(Like.objects.count(), 0)

    def test_post_creates_like_and_second_post_removes_it(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.like_url)
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(Like.objects.filter(user=self.alice, post=self.post).count(), 1)
        self.assertEqual(self.post.likes.count(), 1)

        response = self.client.post(self.like_url)
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(Like.objects.count(), 0)
        self.assertEqual(self.post.likes.count(), 0)

    def test_duplicate_like_is_prevented_by_the_model_constraint(self):
        Like.objects.create(user=self.alice, post=self.post)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Like.objects.create(user=self.alice, post=self.post)


class ToggleLikeRedirectTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.post = Post.objects.create(author=self.alice, caption='Mine')
        self.like_url = reverse('toggle_like', kwargs={'post_id': self.post.pk})
        self.client.force_login(self.alice)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            self.like_url, {'next': 'https://evil.example/'}
        )

        self.assertEqual(response['Location'], reverse('home'))
        self.assertNotIn('evil.example', response['Location'])

    def test_safe_next_is_honoured(self):
        safe_url = reverse('profile_redirect')

        response = self.client.post(self.like_url, {'next': safe_url})

        self.assertEqual(response['Location'], safe_url)


class ImageValidationTests(TemporaryMediaRootMixin, TestCase):
    """Post uploads are checked by gathering.validators.validate_image_upload."""

    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.create_url = reverse('create_post')
        self.client.force_login(self.alice)

    def _upload(self, image, caption=''):
        return self.client.post(
            self.create_url, {'caption': caption, 'image': image}
        )

    def test_valid_jpeg_png_and_webp_are_accepted(self):
        formats = [
            ('JPEG', 'photo.jpg'),
            ('PNG', 'photo.png'),
            ('WEBP', 'photo.webp'),
        ]
        for image_format, name in formats:
            with self.subTest(image_format=image_format):
                response = self._upload(
                    make_test_image(name, image_format=image_format)
                )
                self.assertRedirects(response, reverse('home'))

        self.assertEqual(Post.objects.count(), len(formats))
        for post in Post.objects.all():
            self.assertTrue(os.path.exists(post.image.path))

    def test_image_over_five_megabytes_is_rejected(self):
        image = make_oversized_test_image()
        self.assertGreater(image.size, 5 * 1024 * 1024)

        response = self._upload(image)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertIn('5 MB', str(response.context['form'].errors['image']))
        self.assertContains(response, '5 MB or smaller')

    def test_text_file_named_photo_jpg_is_rejected(self):
        response = self._upload(make_text_upload('photo.jpg'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(response, 'look like a photo')
        self.assertIn('image', response.context['form'].errors)

    def test_gif_is_rejected(self):
        response = self._upload(make_test_image('anim.gif', image_format='GIF'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(response, 'Please upload a JPEG, PNG or WebP image.')

    def test_heic_file_gets_the_iphone_message(self):
        response = self._upload(make_text_upload('IMG_0001.HEIC'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(response, 'HEIC photos need to be converted first')

    def test_image_over_the_pixel_limit_is_rejected(self):
        # 4x4 = 16 pixels, so a limit of 15 trips the rule without building a
        # genuinely huge image.
        with mock.patch('gathering.validators.MAX_IMAGE_PIXELS', 15):
            response = self._upload(make_test_image('big.png', size=(4, 4)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)
        self.assertContains(response, 'too large to process')

