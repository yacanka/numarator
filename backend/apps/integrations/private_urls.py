from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .private_views import PrivateFormatViewSet, PrivateNumberViewSet

router = DefaultRouter()
router.register(r'formats', PrivateFormatViewSet, basename='private-format')
router.register(r'numbers', PrivateNumberViewSet, basename='private-number')

urlpatterns = [path('', include(router.urls))]
