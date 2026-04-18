"""Custom password validators for M01."""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class LettersAndDigitsValidator:
    """Require at least one letter and one digit (plan AC-01-9)."""

    def validate(self, password, user=None):
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise ValidationError(
                _("Password must contain both letters and digits."),
                code="password_missing_letter_or_digit",
            )

    def get_help_text(self):
        return _("Your password must contain both letters and digits.")
