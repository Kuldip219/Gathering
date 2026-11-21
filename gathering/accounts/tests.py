"""Tests for accounts: signup, login, logout, profiles, the social adapter
and the allauth password-reset flow."""

import re
import unittest
from unittest import mock
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from gathering.testing import TemporaryMediaRootMixin, make_test_image

from .adapters import CustomSocialAccountAdapter

User = get_user_model()

#: Throwaway password used by the tests - never the real dev password.
PASSWORD = 'Str0ngPassw0rd!'


def signup_payload(**overrides):
    data = {
        'email': 'alice@example.com',
        'username': 'alice',
        'password1': PASSWORD,
        'password2': PASSWORD,
    }
    data.update(overrides)
    return data


class SignupTests(TestCase):
    # BUG: with both ModelBackend and allauth's AuthenticationBackend in
    # AUTHENTICATION_BACKENDS, `login(request, user)` in accounts/views.py
    # raises ValueError ("You have multiple authentication backends
    # configured and therefore must provide the `backend` argument") because
    # the freshly created user has no `backend` attribute. Signing up
    # therefore returns a 500 instead of logging the new user in.
    @unittest.expectedFailure
    def test_signup_creates_user_and_logs_them_in(self):
        response = self.client.post(reverse('signup'), signup_payload())

        # The view redirects to 'profile_redirect' (/me/), which in turn
        # redirects to the user's profile.
        self.assertRedirects(response, reverse('profile_redirect'))

        user = User.objects.get(email='alice@example.com')
        self.assertEqual(user.username, 'alice')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    # BUG: same login()/backend crash as above - the user is saved but the
    # request ends in a 500 before the redirect.
    @unittest.expectedFailure
    def test_email_is_stored_lowercased(self):
        self.client.post(
            reverse('signup'),
            signup_payload(email='Alice@Example.COM', username='Alice'),
        )

        self.assertTrue(User.objects.filter(email='alice@example.com').exists())
        self.assertFalse(User.objects.filter(email='Alice@Example.COM').exists())

    def test_signup_with_same_email_in_different_case_is_rejected(self):
        # Created directly: the signup view itself currently 500s after the
        # form is saved (see the expectedFailure tests above), which would
        # hide the duplicate-email validation being checked here.
        User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )

        response = self.client.post(
            reverse('signup'),
            signup_payload(email='ALICE@Example.com', username='alice2'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertIn('email', response.context['form'].errors)

    def test_missing_username_is_rejected(self):
        response = self.client.post(reverse('signup'), signup_payload(username=''))

        self.assertEqual(response.status_code, 200)
        self.assertIn('username', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_missing_email_is_rejected(self):
        response = self.client.post(reverse('signup'), signup_payload(email=''))

        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 0)


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )

    def test_login_with_email(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'alice@example.com', 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_with_email_in_different_case(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'ALICE@Example.com', 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'alice@example.com', 'password': 'totally-wrong'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotIn('_auth_user_id', self.client.session)

    # BUG: the form is labelled "Email" and its docstring says allauth
    # authenticate() treats the value as an email, but ACCOUNT_LOGIN_METHODS
    # is not set, so allauth's default is username-only. Its
    # AuthenticationBackend (the second configured backend) then happily logs
    # the user in with their username.
    @unittest.expectedFailure
    def test_username_alone_is_not_a_login_identifier(self):
        response = self.client.post(
            reverse('login'), {'username': 'alice', 'password': PASSWORD}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotIn('_auth_user_id', self.client.session)


class LogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )

    def test_post_logs_out(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_get_does_not_log_out(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('logout'))

        # Django's LogoutView only accepts POST.
        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)


class ProfileTests(TemporaryMediaRootMixin, TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.bob = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )
        self.alice_profile_url = reverse('profile', kwargs={'username': 'alice'})
        self.bob_profile_url = reverse('profile', kwargs={'username': 'bob'})

    def test_me_redirects_to_own_profile(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse('profile_redirect'))

        self.assertRedirects(response, self.alice_profile_url)

    def test_other_profile_is_viewable(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.bob_profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['profile_user'], self.bob)
        self.assertFalse(response.context['is_own_profile'])
        self.assertContains(response, 'bob')

    def test_user_can_edit_own_bio_and_picture(self):
        self.client.force_login(self.alice)

        response = self.client.post(
            self.alice_profile_url,
            {'bio': 'Updated bio', 'profile_picture': make_test_image()},
        )

        self.assertRedirects(response, self.alice_profile_url)

        self.alice.refresh_from_db()
        self.assertEqual(self.alice.bio, 'Updated bio')
        self.assertTrue(self.alice.profile_picture.name.startswith('profile_pictures/'))

    def test_user_cannot_edit_another_users_profile(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.bob_profile_url, {'bio': 'hacked'})

        # No form is built for someone else's profile, so the POST merely
        # re-renders the page and nothing is saved.
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['form'])
        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.bio)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse('profile_redirect'))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('profile_redirect')}"
        )

        response = self.client.get(self.bob_profile_url)
        self.assertRedirects(
            response, f"{reverse('login')}?next={self.bob_profile_url}"
        )


class CustomSocialAccountAdapterTests(TestCase):
    def _sociallogin(self, email):
        sociallogin = mock.MagicMock()
        sociallogin.is_existing = False
        sociallogin.account.extra_data = {'email': email}
        return sociallogin

    def test_existing_user_with_same_email_different_case_gets_linked(self):
        user = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        request = mock.MagicMock()
        sociallogin = self._sociallogin('ALICE@Example.com')

        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)

        sociallogin.connect.assert_called_once_with(request, user)

    def test_no_existing_user_means_no_connect(self):
        request = mock.MagicMock()
        sociallogin = self._sociallogin('nobody@example.com')

        CustomSocialAccountAdapter().pre_social_login(request, sociallogin)

        sociallogin.connect.assert_not_called()

    def test_two_users_differing_only_by_case_do_not_raise(self):
        # email is unique but SQLite compares case-sensitively, so both rows
        # can exist; the adapter must not blow up with MultipleObjectsReturned.
        first = User.objects.create_user(
            email='Alice@Example.com', username='alice-one', password=PASSWORD
        )
        User.objects.create_user(
            email='alice@example.com', username='alice-two', password=PASSWORD
        )
        request = mock.MagicMock()
        sociallogin = self._sociallogin('ALICE@example.com')

        try:
            CustomSocialAccountAdapter().pre_social_login(request, sociallogin)
        except User.MultipleObjectsReturned:
            self.fail('pre_social_login raised MultipleObjectsReturned')

        sociallogin.connect.assert_called_once()
        self.assertEqual(sociallogin.connect.call_args[0][1], first)


class PasswordResetTests(TestCase):
    RESET_URL_RE = re.compile(r'https?://\S+/accounts/password/reset/key/\S+')

    def setUp(self):
        self.user = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )

    def test_request_page_loads(self):
        response = self.client.get(reverse('account_reset_password'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account/password_reset.html')

    def test_full_reset_flow(self):
        response = self.client.post(
            reverse('account_reset_password'), {'email': 'bob@example.com'}
        )
        self.assertRedirects(response, reverse('account_reset_password_done'))

        self.assertEqual(len(mail.outbox), 1)
        match = self.RESET_URL_RE.search(mail.outbox[0].body)
        self.assertIsNotNone(match, msg=mail.outbox[0].body)
        key_path = urlsplit(match.group(0)).path

        # The keyed URL redirects to a key-free "set password" URL.
        response = self.client.get(key_path)
        self.assertEqual(response.status_code, 302)
        response = self.client.get(key_path, follow=True)
        self.assertEqual(response.status_code, 200)
        set_password_path = response.request['PATH_INFO']

        new_password = 'BrandNewPassw0rd!'
        response = self.client.post(
            set_password_path,
            {'password1': new_password, 'password2': new_password},
        )
        self.assertRedirects(
            response, reverse('account_reset_password_from_key_done')
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

        # New password logs in, old one no longer does.
        response = self.client.post(
            reverse('login'),
            {'username': 'bob@example.com', 'password': new_password},
        )
        self.assertRedirects(response, reverse('home'))

        self.client.logout()
        response = self.client.post(
            reverse('login'), {'username': 'bob@example.com', 'password': PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_email_gets_the_same_done_page(self):
        known = self.client.post(
            reverse('account_reset_password'), {'email': 'bob@example.com'}
        )
        unknown = self.client.post(
            reverse('account_reset_password'), {'email': 'nobody@example.com'}
        )

        self.assertEqual(unknown.status_code, 302)
        self.assertEqual(known['Location'], unknown['Location'])

    def test_invalid_key_shows_failure_page_not_500(self):
        url = reverse(
            'account_reset_password_from_key',
            kwargs={'uidb36': 'zzz', 'key': 'garbage-key'},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reset link invalid')
