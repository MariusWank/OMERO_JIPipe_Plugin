import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid

from pathlib import Path
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

import omero
import omero.model
from omero.rtypes import rstring
from omeroweb.decorators import login_required

# Directory where JIPipe log files are stored (customize via Django settings)
LOG_DIR = getattr(settings, 'JIPIPE_LOG_ROOT', '/tmp/jipipe_logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Time (in seconds) to keep PIDs in cache before expiring (None == never expire)
CACHE_TIMEOUT: Optional[int] = None

def _run_jipipe_thread(project_config: dict, job_uuid: str, omero_conn, log_file_path: str) -> None:
    """
    Execute JIPipe CLI in a background thread and stream its output to a log file.
    """
    log = logging.getLogger(__name__)

    # Create temporary directories for input and output data
    temp_input = tempfile.mkdtemp()
    temp_output = tempfile.mkdtemp()

    try:
        # Write the JIPipe project configuration to a .jip file
        jip_project_file = Path(temp_input) / 'JIPipeProject.jip'
        with open(jip_project_file, 'w') as jip_file:
            json.dump(project_config, jip_file)

        # Build the JIPipe CLI command
        command = [
            'xvfb-run', '-a',
            '/opt/JIPipe-4.2/Fiji.app/ImageJ-linux64',
            '-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=ERROR',
            '-Dorg.apache.logging.log4j.simplelog.level=ERROR',
            '--memory', '8G',
            '--pass-classpath',
            '--full-classpath',
            '--main-class', 'org.hkijena.jipipe.cli.JIPipeCLIMain',
            'run',
            '--project', str(jip_project_file),
            '--output-folder', temp_output,
        ]

        # Launch the process and stream stdout/stderr to the log file
        with open(log_file_path, 'w') as log_file:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )

            # Store its PID in Redis
            cache.set(job_uuid, process.pid, timeout=CACHE_TIMEOUT)

            for line in process.stdout:
                log_file.write(line)
                log_file.flush()

            process.wait()
            log_file.write(f"\n[ JIPipe exited with code {process.returncode} ]\n")

    except Exception as error:
        # Log any exceptions to the same log file
        with open(log_file_path, 'a') as log_file:
            log_file.write(f"\nERROR in JIPipe background job: {error}\n")
        log.error("Error during JIPipe execution: %s", error)

    finally:
        # Clean up the temporary input directory and delete the PID from cache
        cache.delete(job_uuid)
        owner = omero_conn.getUser().getName()
        user_key = f"active_jipipe_jobs_{owner}"
        active = set(cache.get(user_key, []))
        active.discard(job_uuid)
        cache.set(user_key, active, timeout=CACHE_TIMEOUT)
        shutil.rmtree(temp_input)
        shutil.rmtree(temp_output)


@require_POST
@login_required()
def start_jipipe_job(request, conn=None, **kwargs) -> JsonResponse:
    """
    Start a JIPipe job in the background.

    Expects a JSON payload describing the project graph.
    Returns JSON with a unique job ID.

    URL: JIPipeRunner/start_jipipe_job/
    """
    # Parse the incoming configuration
    project_config = json.loads(request.body.decode('utf-8'))

    # Always run as the default OMERO group
    conn.SERVICE_OPTS.setOmeroGroup('0')

    # Ensure there is a JIPipeResults project to store outputs
    results_project = _get_or_create_results_project(conn)
    results_project_id = int(results_project.getId())

    # Assign dataset IDs for define-project-ids nodes
    for node in project_config.get('graph', {}).get('nodes', {}).values():
        alias = node.get('jipipe:alias-id', '').lower()
        if 'define-project-ids' in alias:
            node['dataset-ids'] = [results_project_id]

    # Prepare the log file path and unique job identifier
    job_uuid = uuid.uuid4().hex
    log_file = os.path.join(LOG_DIR, f'{job_uuid}.log')

    owner = conn.getUser().getName()
    user_key = f"active_jipipe_jobs_{owner}"
    active = set(cache.get(user_key, []))
    active.add(job_uuid)
    cache.set(user_key, active, timeout=CACHE_TIMEOUT)

    # Launch the background thread
    threading.Thread(
        target=_run_jipipe_thread,
        args=(project_config, job_uuid, conn, log_file),
        daemon=True,
    ).start()

    return JsonResponse({'job_id': job_uuid})

@require_POST
@login_required()
def stop_jipipe_job(request, conn=None, **kwargs) -> JsonResponse:
    """
    Stop a running JIPipe job by job_id.  
    Expects JSON: { "job_id": "<uuid>" }
    """
    try:
        data = json.loads(request.body)
        job_id = data.get('job_id')
        if not job_id:
            return JsonResponse({'error': 'Missing job_id'}, status=400)

        pid = cache.get(job_id)
        if not pid:
            return JsonResponse({'error': 'Job not found or already finished'}, status=404)
        
        owner = conn.getUser().getName()
        user_key = f"active_jipipe_jobs_{owner}"
        active = set(cache.get(user_key, []))
        if job_id not in active:
            return JsonResponse({'error': 'Job not found or not owned by you'}, status=404)

        # Send SIGTERM to the process group
        os.killpg(pid, signal.SIGTERM)
        cache.delete(job_id)

        active.discard(job_id)
        cache.set(user_key, active, timeout=CACHE_TIMEOUT)

        return JsonResponse({'status': 'terminated', 'job_id': job_id})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

@require_GET
@login_required()
def list_jipipe_jobs(request, conn=None, **kwargs):
    owner = conn.getUser().getName()
    user_key = f"active_jipipe_jobs_{owner}"
    job_ids = cache.get(user_key, [])
    return JsonResponse({'job_ids': list(job_ids)})

@require_GET
@login_required()
def fetch_jipipe_logs(request, job_id: str, **kwargs) -> JsonResponse:
    """
    Return the status and accumulated logs for a running or finished JIPipe job.

    URL: JIPipeRunner/fetch_jipipe_logs/<job_id>
    """
    log_file = os.path.join(LOG_DIR, f'{job_id}.log')

    if not os.path.exists(log_file):
        raise Http404(f'Job not found: {job_id}')

    with open(log_file, 'r') as file_handle:
        log_lines = file_handle.read().splitlines()

    # Determine if the job finished by checking for the exit code message
    finished = any('JIPipe exited with code' in line for line in log_lines[-3:])
    status = 'finished' if finished else 'running'

    return JsonResponse({'status': status, 'logs': log_lines})


@login_required()
def jipipe_runner_index(request, project_id: int, conn=None, **kwargs) -> HttpResponse:
    """
    Display the dataset input form for a given OMERO project.
    """
    return render(
        request,
        'JIPipeRunner/dataset_input.html',
        {'project_id': project_id}
    )


@login_required()
def get_jipipe_config(request, project_id: int, conn=None, **kwargs) -> JsonResponse:
    """
    Fetch the JIPipe JSON configuration stored as a FileAnnotation on the project.
    """
    logger = logging.getLogger(__name__)
    conn.SERVICE_OPTS.setOmeroGroup('0')

    project = conn.getObject('Project', project_id)
    if project is None:
        return HttpResponse(f'Project {project_id} not found.', status=404)

    # Find the first FileAnnotation attached to the project
    annotation = next(
        (ann for ann in project.listAnnotations()
         if ann.OMERO_TYPE == omero.model.FileAnnotationI),
        None,
    )

    if annotation is None:
        return HttpResponse(
            f'No JIPipe configuration found for project {project_id}.',
            status=404,
        )

    try:
        # Read and parse the JSON data from the annotation
        raw_bytes = b''.join(annotation.getFileInChunks())
        config_text = raw_bytes.decode('utf-8')
        config_data = json.loads(config_text)
    except Exception as parse_error:
        logger.error('Failed to parse JIPipe JSON: %s', parse_error)
        return HttpResponse(
            f'Error parsing JIPipe JSON: {parse_error}',
            status=400,
        )

    return JsonResponse(config_data, safe=False)


# Helper: ensure the results project exists

def _get_or_create_results_project(conn) -> omero.gateway.ProjectWrapper:
    project_name = 'JIPipeResults'

    # Attempt to find an existing project
    existing = conn.getObject('Project', attributes={'name': project_name})
    if existing:
        return existing

    # Create a new Project model and save it
    new_project_model = omero.model.ProjectI()
    new_project_model.setName(rstring(project_name))
    new_project_model.setDescription(rstring('Project to save all JIPipe results'))

    saved_model = conn.getUpdateService().saveAndReturnObject(
        new_project_model,
        conn.SERVICE_OPTS,
    )

    new_id = saved_model.getId().getValue()
    return conn.getObject('Project', new_id)
