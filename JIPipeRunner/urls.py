from django.urls import path
from . import views

urlpatterns = [
    path('jipipe_runner_index/', views.jipipe_runner_index, name='jipipe_runner_index'),
    path('get_jipipe_config/<int:jip_file_id>/', views.get_jipipe_config, name='get_jipipe_config'),
    path("jipipe_start_job/", views.start_jipipe_job, name="jipipe_start_job"),
    path("fetch_jipipe_logs/<str:job_uuid>/", views.fetch_jipipe_logs, name="fetch_jipipe_logs"),
    path("stop_jipipe_job/", views.stop_jipipe_job, name="stop_jipipe_job"),
    path("list_jipipe_jobs/", views.list_jipipe_jobs, name="list_jipipe_jobs"),
    path("list_jipipe_files/", views.list_jipipe_files, name="list_jipipe_files"),
]