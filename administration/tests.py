from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from administration.models import Department, Faculty


class UserProfileRelationTests(TestCase):
    def setUp(self):
        self.faculty_a = Faculty.objects.create(name="Faculty A")
        self.faculty_b = Faculty.objects.create(name="Faculty B")
        self.department_a = Department.objects.create(
            name="Dept A", faculty=self.faculty_a
        )
        self.department_b = Department.objects.create(
            name="Dept B", faculty=self.faculty_b
        )

    def test_user_creation_creates_profile_without_department(self):
        user = User.objects.create_user(username="user1", password="x")
        self.assertTrue(hasattr(user, "profile"))
        self.assertIsNone(user.profile.faculty)
        self.assertIsNone(user.profile.department)

    def test_profile_infers_faculty_from_department(self):
        user = User.objects.create_user(username="user2", password="x")
        profile = user.profile
        profile.department = self.department_a
        profile.save()

        profile.refresh_from_db()
        self.assertEqual(profile.faculty, self.faculty_a)

    def test_profile_rejects_mismatched_department_and_faculty(self):
        user = User.objects.create_user(username="user3", password="x")
        profile = user.profile
        profile.faculty = self.faculty_a
        profile.department = self.department_b

        with self.assertRaises(ValidationError):
            profile.save()
