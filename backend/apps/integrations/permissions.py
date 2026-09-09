from rest_framework.permissions import BasePermission

from .models import ApiCredential


class HasApiScope(BasePermission):
    """Require the scope declared by the private API action."""

    message = 'The API key does not have the required scope.'

    def has_permission(self, request, view):
        credential = request.auth
        if not isinstance(credential, ApiCredential):
            return False
        required_scope = view.get_required_scope()
        return required_scope is None or required_scope in credential.scopes
