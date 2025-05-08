from django.urls import path
from . import views

urlpatterns = [
    path('JIPipeRunner_index/<int:project_id>', views.jipipe_runner_index, name='JIPipeRunner_index'),
    path('getJIPipeJSON/<int:project_id>/json/', views.get_jipipe_config, name='getJIPipeJSON'),
    path("jipipe_start_job/", views.start_jipipe_job, name="jipipe_start_job"),
    path("fetch_jipipe_logs/<str:job_id>/", views.fetch_jipipe_logs, name="fetch_jipipe_logs"),
]