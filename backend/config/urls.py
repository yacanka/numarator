# config/urls.py
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/', include('apps.formats.urls')),
    path('api/v1/', include('apps.documents.urls')),
    path('api/v1/auth/', include('apps.core.auth_urls')),
    path('api/v1/integrations/', include('apps.integrations.urls')),
    path('api/private/v1/', include('apps.integrations.private_urls')),
]
