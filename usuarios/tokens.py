from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ActivacionTokenGenerator(PasswordResetTokenGenerator):
    """Tokens de activación separados de los tokens nativos de recuperación."""

    key_salt = "usuarios.tokens.ActivacionTokenGenerator"


activacion_token_generator = ActivacionTokenGenerator()
