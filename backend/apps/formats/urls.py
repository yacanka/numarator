# apps/formats/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DocumentFormatViewSet, FormatCategoryViewSet

router = DefaultRouter()
router.register(r'formats', DocumentFormatViewSet, basename='format')
router.register(r'categories', FormatCategoryViewSet, basename='category')

urlpatterns = [path('', include(router.urls))]