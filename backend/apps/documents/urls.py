# apps/documents/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import GeneratedDocumentViewSet

router = DefaultRouter()
router.register(r'documents', GeneratedDocumentViewSet, basename='document')

urlpatterns = [path('', include(router.urls))]