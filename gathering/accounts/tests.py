"""Tests for accounts: signup, login, logout, profiles, the social adapter
and the allauth password-reset flow."""

import re
from unittest import mock
from urllib.parse import urlsplit

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from gathering.testing import (
    TemporaryMediaRootMixin,
    make_oversized_test_image,
    make_test_image,
    make_text_upload,
)

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
    def test_signup_creates_user_and_logs_them_in(self):
        response = self.client.post(reverse('signup'), signup_payload())

        # The view redirects to 'profile_redirect' (/me/), which in turn
        # redirects to the user's profile, so don't fetch that URL.
        self.assertRedirects(
            response, reverse('profile_redirect'), fetch_redirect_response=False
        )

        user = User.objects.get(email='alice@example.com')
        self.assertEqual(user.username, 'alice')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_signup_leaves_the_user_logged_in_on_the_home_feed(self):
        self.client.post(reverse('signup'), signup_payload())

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'posts/home.html')
        self.assertEqual(int(self.client.session['_auth_user_id']),
                         User.objects.get(email='alice@example.com').pk)

    def test_signup_user_can_log_out_and_back_in_with_email(self):
        self.client.post(reverse('signup'), signup_payload())
        user = User.objects.get(email='alice@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

        # Log in the way a real user does: email as the identifier.
        response = self.client.post(
            reverse('login'),
            {'username': 'alice@example.com', 'password': PASSWORD},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

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


class ProfilePictureValidationTests(TemporaryMediaRootMixin, TestCase):
    """Profile uploads go through gathering.validators.validate_image_upload."""

    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.profile_url = reverse('profile', kwargs={'username': 'alice'})
        self.client.force_login(self.alice)

    def _post(self, **data):
        return self.client.post(self.profile_url, data)

    def test_valid_jpeg_png_and_webp_are_accepted(self):
        formats = [
            ('JPEG', 'photo.jpg'),
            ('PNG', 'photo.png'),
            ('WEBP', 'photo.webp'),
        ]
        for image_format, name in formats:
            with self.subTest(image_format=image_format):
                response = self._post(
                    bio=f'Uploaded {image_format}',
                    profile_picture=make_test_image(name, image_format=image_format),
                )

                self.assertRedirects(response, self.profile_url)
                self.alice.refresh_from_db()
                self.assertTrue(
                    self.alice.profile_picture.name.startswith('profile_pictures/')
                )

    def test_bio_edit_without_a_new_picture_still_works(self):
        self._post(bio='First bio', profile_picture=make_test_image('first.png'))
        self.alice.refresh_from_db()
        kept_picture = self.alice.profile_picture.name

        response = self._post(bio='Second bio')

        self.assertRedirects(response, self.profile_url)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.bio, 'Second bio')
        self.assertEqual(self.alice.profile_picture.name, kept_picture)

    def test_bad_image_leaves_the_old_picture_unchanged(self):
        self._post(bio='Keep this', profile_picture=make_test_image('old.png'))
        self.alice.refresh_from_db()
        kept_picture = self.alice.profile_picture.name

        response = self._post(bio='Should not save', profile_picture=make_text_upload())

        self.assertEqual(response.status_code, 200)
        self.assertIn('profile_picture', response.context['form'].errors)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.profile_picture.name, kept_picture)
        self.assertEqual(self.alice.bio, 'Keep this')

    def test_image_over_five_megabytes_is_rejected(self):
        image = make_oversized_test_image()
        self.assertGreater(image.size, 5 * 1024 * 1024)

        response = self._post(bio='Too big', profile_picture=image)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.alice.profile_picture)
        self.assertContains(response, '5 MB or smaller')

    def test_text_file_named_photo_jpg_is_rejected(self):
        response = self._post(profile_picture=make_text_upload())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.alice.profile_picture)
        self.assertContains(response, 'look like a photo')

    def test_gif_is_rejected(self):
        response = self._post(
            profile_picture=make_test_image('anim.gif', image_format='GIF')
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.alice.profile_picture)
        self.assertContains(response, 'Please upload a JPEG, PNG or WebP image.')

    def test_image_over_the_pixel_limit_is_rejected(self):
        with mock.patch('gathering.validators.MAX_IMAGE_PIXELS', 15):
            response = self._post(
                profile_picture=make_test_image('big.png', size=(4, 4))
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.alice.profile_picture)
        self.assertContains(response, 'too large to process')

    def test_picture_input_accepts_image_types(self):
        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accept="image/jpeg,image/png,image/webp"')


class AccountMenuTests(TestCase):
    """The account menu, shared by every logged-in page via the nav partial."""

    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.bob = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )

    def assertAccountMenu(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="account-menu-button"')
        self.assertContains(response, 'id="account-menu-panel"')
        self.assertContains(response, f'href="{reverse("profile_redirect")}"')
        self.assertContains(
            response, f'href="{reverse("profile", kwargs={"username": "alice"})}"'
        )
        # Log out must be a POST form carrying a CSRF token.
        self.assertContains(response, f'action="{reverse("logout")}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_logged_in_home_shows_the_menu_with_links_and_logout_form(self):
        self.client.force_login(self.alice)

        self.assertAccountMenu(self.client.get(reverse('home')))

    def test_own_profile_page_shows_the_menu(self):
        self.client.force_login(self.alice)

        response = self.client.get(
            reverse('profile', kwargs={'username': 'alice'})
        )

        self.assertAccountMenu(response)

    def test_another_users_profile_page_shows_the_menu(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse('profile', kwargs={'username': 'bob'}))

        self.assertAccountMenu(response)

    def test_create_post_page_shows_the_menu(self):
        self.client.force_login(self.alice)

        self.assertAccountMenu(self.client.get(reverse('create_post')))

    def test_navbar_wordmark_links_to_the_feed(self):
        self.client.force_login(self.alice)
        pages = [
            reverse('home'),
            reverse('profile', kwargs={'username': 'alice'}),
            reverse('create_post'),
        ]
        expected = r'<a href="%s"[^>]*>\s*Gathering\s*</a>' % re.escape(
            reverse('home')
        )

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertRegex(response.content.decode(), expected)

    def test_profile_page_has_no_back_to_feed_link(self):
        self.client.force_login(self.alice)

        response = self.client.get(
            reverse('profile', kwargs={'username': 'alice'})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Back to feed')

    def test_anonymous_login_page_has_no_account_menu(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'account-menu-button')
        self.assertNotContains(response, 'account-menu-panel')

    def test_signup_page_has_no_account_menu(self):
        response = self.client.get(reverse('signup'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'account-menu-button')
        self.assertNotContains(response, 'account-menu-panel')

    def test_logout_post_from_the_menu_logs_the_user_out(self):
        self.client.force_login(self.alice)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ChangeEmailTests(TestCase):
    """Changing the login email from /account/email/."""

    def setUp(self):
        self.alice = User.objects.create_user(
            email='alice@example.com', username='alice', password=PASSWORD
        )
        self.bob = User.objects.create_user(
            email='bob@example.com', username='bob', password=PASSWORD
        )
        self.url = reverse('change_email')
        self.profile_url = reverse('profile', kwargs={'username': 'alice'})

    def _post(self, **overrides):
        data = {
            'new_email': 'alice.new@example.com',
            'current_password': PASSWORD,
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_anonymous_get_and_post_redirect_to_login(self):
        get_response = self.client.get(self.url)
        post_response = self.client.post(
            self.url, {'new_email': 'x@example.com', 'current_password': PASSWORD}
        )

        self.assertRedirects(
            get_response, f'{reverse("login")}?next={self.url}', fetch_redirect_response=False
        )
        self.assertRedirects(
            post_response, f'{reverse("login")}?next={self.url}', fetch_redirect_response=False
        )
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')

    def test_page_renders_and_account_menu_links_to_it(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{self.url}"')
        self.assertContains(response, 'Edit email')
        self.assertContains(response, 'Current password')

    def test_successful_change_updates_email_notifies_old_address_and_keeps_login(self):
        self.client.force_login(self.alice)

        response = self._post(new_email='Alice.New@Example.COM ')

        self.assertRedirects(response, self.profile_url)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice.new@example.com')

        self.assertEqual(len(mail.outbox), 1)
        notice = mail.outbox[0]
        self.assertEqual(notice.to, ['alice@example.com'])
        self.assertIn('alice.new@example.com', notice.body)
        self.assertNotIn(PASSWORD, notice.body)

        # The session must survive the change.
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)

    def test_wrong_password_changes_nothing(self):
        self.client.force_login(self.alice)

        response = self._post(current_password='not-the-password')

        self.assertEqual(response.status_code, 200)
        self.assertIn('current_password', response.context['form'].errors)
        self.assertContains(response, 'not correct')
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_password_is_rejected_for_users_who_have_one(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.url, {'new_email': 'alice.new@example.com'})

        self.assertEqual(response.status_code, 200)
        # The password field is required whenever the account has a password.
        self.assertIn('current_password', response.context['form'].errors)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_email_used_by_another_user_is_rejected_case_insensitively(self):
        self.client.force_login(self.alice)

        response = self._post(new_email='BOB@Example.com')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A user with that email already exists.')
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_same_email_is_rejected(self):
        self.client.force_login(self.alice)

        response = self._post(new_email='ALICE@example.com')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already your login email')
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')

    def test_google_only_account_does_not_need_a_password(self):
        self.alice.set_unusable_password()
        self.alice.save()
        self.client.force_login(self.alice)

        page = self.client.get(self.url)
        response = self.client.post(self.url, {'new_email': 'alice.new@example.com'})

        self.assertNotContains(page, 'Current password')
        self.assertContains(page, 'signs in with Google')
        self.assertRedirects(response, self.profile_url)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice.new@example.com')

    def test_allauth_email_address_rows_follow_the_change(self):
        EmailAddress.objects.create(
            user=self.alice, email='alice@example.com', primary=True, verified=True
        )
        self.client.force_login(self.alice)

        response = self._post()

        self.assertRedirects(response, self.profile_url)
        remaining = list(EmailAddress.objects.filter(user=self.alice))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].email, 'alice.new@example.com')
        self.assertTrue(remaining[0].primary)
        self.assertFalse(
            EmailAddress.objects.filter(email__iexact='alice@example.com').exists()
        )

    def test_login_with_new_email_works_and_old_email_no_longer_does(self):
        self.client.force_login(self.alice)
        self._post()
        self.client.logout()

        new_login = self.client.post(
            reverse('login'),
            {'username': 'alice.new@example.com', 'password': PASSWORD},
        )
        self.assertRedirects(new_login, reverse('home'))

        self.client.logout()
        old_login = self.client.post(
            reverse('login'),
            {'username': 'alice@example.com', 'password': PASSWORD},
        )
        self.assertEqual(old_login.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_email_is_rejected(self):
        self.client.force_login(self.alice)

        response = self._post(new_email='not-an-email')

        self.assertEqual(response.status_code, 200)
        self.assertIn('new_email', response.context['form'].errors)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'alice@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_follows_the_new_address_and_not_the_old_one(self):
        # A Google-style account: allauth keeps the primary address in its own
        # table, which is what password reset resolves recipients through.
        EmailAddress.objects.create(
            user=self.alice, email='alice@example.com', primary=True, verified=True
        )
        self.client.force_login(self.alice)
        self._post()
        self.client.logout()
        mail.outbox = []

        new_reset = self.client.post(
            reverse('account_reset_password'), {'email': 'alice.new@example.com'}
        )

        self.assertRedirects(new_reset, reverse('account_reset_password_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['alice.new@example.com'])

        self.assertEqual(
            list(
                EmailAddress.objects.filter(user=self.alice).values_list(
                    'email', 'primary'
                )
            ),
            [('alice.new@example.com', True)],
        )

        # A genuinely unknown address is the yardstick for "no reset happened".
        mail.outbox = []
        self.client.post(
            reverse('account_reset_password'), {'email': 'nobody@example.com'}
        )
        unknown_subjects = [m.subject for m in mail.outbox]

        mail.outbox = []
        old_reset = self.client.post(
            reverse('account_reset_password'), {'email': 'alice@example.com'}
        )

        self.assertRedirects(old_reset, reverse('account_reset_password_done'))
        self.assertEqual([m.subject for m in mail.outbox], unknown_subjects)
        self.assertEqual([m.to for m in mail.outbox], [['alice@example.com']])
        # Above all: no password-reset link was sent to the old address.
        self.assertFalse(
            any(
                PasswordResetTests.RESET_URL_RE.search(message.body)
                for message in mail.outbox
            )
        )

    def test_a_user_cannot_change_another_users_email(self):
        self.client.force_login(self.alice)

        # Extra fields trying to point the edit at bob must be ignored.
        response = self.client.post(
            self.url,
            {
                'new_email': 'alice.moved@example.com',
                'current_password': PASSWORD,
                'user': self.bob.pk,
                'user_id': self.bob.pk,
                'pk': self.bob.pk,
            },
        )

        self.assertRedirects(response, self.profile_url)
        self.bob.refresh_from_db()
        self.alice.refresh_from_db()
        self.assertEqual(self.bob.email, 'bob@example.com')
        self.assertEqual(self.alice.email, 'alice.moved@example.com')
