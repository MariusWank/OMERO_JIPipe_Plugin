from django.urls import path
from . import views

urlpatterns = [
    path('process_datasets/', views.process_datasets, name='process_datasets'),
    path('JIPipeRunner_index/<int:project_id>', views.JIPipeRunner_index, name='JIPipeRunner_index'),
    path('getJIPipeJSON/<int:project_id>/json/', views.getJIPipeJSON, name='getJIPipeJSON'),
    path("start_job/", views.start_job, name="jipipe_start_job"),
    path("fetch_logs/<str:job_id>/", views.fetch_logs, name="jipipe_fetch_logs"),
]