from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EmployeeViewset

router = DefaultRouter()
router.register(r'employee', EmployeeViewset, basename='users')

urlpatterns = [
 path('', include(router.urls)),
]
