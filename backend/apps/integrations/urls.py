from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ApiCredentialViewSet

router = DefaultRouter()
router.register(r'api-keys', ApiCredentialViewSet, basename='api-key')

urlpatterns = [path('', include(router.urls))]
