import os
import re
import json
import time
import tempfile
import shutil
import logging
import subprocess
from pathlib import Path
import uuid
import threading

from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse, Http404
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

import omero
import omero.model
from omero.rtypes import rstring
from omeroweb.decorators import login_required

# Optional imports for future extensions
# import numpy as np
# from PIL import Image
# import cv2

# Mapping of file extensions to Pillow formats
EXTENSION_TO_FORMAT = {
    '.jpg': 'JPEG',
    '.jpeg': 'JPEG',
    '.png': 'PNG',
    '.tiff': 'TIFF',
    '.tif': 'TIFF',
    '.bmp': 'BMP',
}

# You can customize this in your Django settings if you like.
LOG_ROOT = getattr(settings, "JIPIPE_LOG_ROOT", "/tmp/jipipe_logs")
os.makedirs(LOG_ROOT, exist_ok=True)

def _run_jipipe(config, job_id, conn, log_path):
    """
    Background thread: run JIPipe and stream stdout → shared log file.
    """
    logger = logging.getLogger(__name__)
    input_tmp = tempfile.mkdtemp()
    output_tmp = tempfile.mkdtemp()
    try:
        # write the .jip file
        jip_file = Path(input_tmp) / "JIPipeProject.jip"
        with open(jip_file, "w") as fp:
            json.dump(config, fp)

        # build and launch the CLI
        cmd = [
            "xvfb-run", "-a",
            "/opt/JIPipe-4.2/Fiji.app/ImageJ-linux64",
            "-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=ERROR",
            "-Dorg.apache.logging.log4j.simplelog.level=ERROR",
            "--memory", "8G",
            "--pass-classpath",
            "--full-classpath",
            "--main-class", "org.hkijena.jipipe.cli.JIPipeCLIMain",
            "run",
            "--project", str(jip_file),
            "--output-folder", output_tmp,
        ]
        with open(log_path, "w") as log:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in proc.stdout:
                log.write(line)
                log.flush()
            proc.wait()
            log.write(f"\n[ JIPipe exited with code {proc.returncode} ]\n")
    except Exception as e:
        with open(log_path, "a") as log:
            log.write(f"\nERROR in background job: {e}\n")
    finally:
        shutil.rmtree(input_tmp)
        # leave output_tmp around if you need it


@csrf_exempt
@require_POST
@login_required()
def start_job(request, conn=None, **kwargs):
    """
    Starts JIPipe in a background thread.
    Returns JSON: { job_id: str }.
    """
    # 1) Parse & patch config (same as before)
    payload = json.loads(request.body.decode("utf-8"))
    conn.SERVICE_OPTS.setOmeroGroup("0")
    project = _get_or_create_results_project(conn)
    project_id = int(project.getId())
    for node in payload.get("graph", {}).get("nodes", {}).values():
        if "define-project-ids" in node.get("jipipe:alias-id", "").lower():
            node["dataset-ids"] = [project_id]

    # 2) Spin up the job
    job_id = uuid.uuid4().hex
    log_path = os.path.join(LOG_ROOT, f"{job_id}.log")

    # Background thread writes to that log_path
    threading.Thread(
        target=_run_jipipe,
        args=(payload, job_id, conn, log_path),
        daemon=True
    ).start()

    return JsonResponse({"job_id": job_id})


@require_GET
@login_required()
def fetch_logs(request, job_id, **kwargs):
    """
    Poll this to get status & log lines so far.
    Returns JSON: { status: "running"|"finished", logs: [ str, ... ] }.
    """
    log_path = os.path.join(LOG_ROOT, f"{job_id}.log")
    if not os.path.exists(log_path):
        raise Http404(f"No such job {job_id}")

    with open(log_path, "r") as f:
        lines = f.read().splitlines()

    # detect if finished by looking for the exit‐code footnote
    finished = any("JIPipe exited with code" in line for line in lines[-3:])
    status = "finished" if finished else "running"

    return JsonResponse({"status": status, "logs": lines})


@csrf_exempt
@require_POST
@login_required()
def process_datasets(request, conn=None, **kwargs):
    """
    Receive a JIPipe JSON, write it to a .jip file, execute the JIPipe CLI,
    and return processing results or errors.
    """
    logger = logging.getLogger(__name__)
    conn.SERVICE_OPTS.setOmeroGroup('0')
    input_temp_dir = tempfile.mkdtemp()
    output_temp_dir = tempfile.mkdtemp()
    input_path = Path(input_temp_dir)
    output_path = Path(output_temp_dir)

    try:
        # Parse and modify incoming JSON
        content = request.body.decode('utf-8')
        config = json.loads(content)
        logger.info("Received pipeline configuration JSON")

        # Ensure or create JIPipeResults project
        project = _get_or_create_results_project(conn)
        project_id = int(project.getId())

        # Assign any define-project-ids nodes to results project
        for node in config.get('graph', {}).get('nodes', {}).values():
            alias = node.get('jipipe:alias-id', '').lower()
            if 'define-project-ids' in alias:
                node['dataset-ids'] = [project_id]

        # Write .jip file
        jip_file = input_path / 'JIPipeProject.jip'
        with jip_file.open('w') as fp:
            json.dump(config, fp)

        # Build and run JIPipe CLI command
        cli_path = Path("/opt/JIPipe-4.2/Fiji.app/ImageJ-linux64")
        # Build the command as before
        command = [
            'xvfb-run', '-a',
            str(cli_path),
            '-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=ERROR',
            '-Dorg.apache.logging.log4j.simplelog.level=ERROR',
            '--memory', '8G',
            '--pass-classpath',
            '--full-classpath',
            '--main-class', 'org.hkijena.jipipe.cli.JIPipeCLIMain',
            'run',
            '--project', str(jip_file),
            '--output-folder', str(output_path),
        ]

        # Launch the process
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )

        # Generator that yields lines as they come
        def stream():
            info_rx = re.compile(r'^\[INFO\]|^\[WARNING\]|\bwarning\b|^ERROR StatusLogger|^HTTP/')
            yield "JIPipeRunner started, please be patient!\n"

            hb_interval = 5.0
            last = time.time()

            while True:
                line = proc.stdout.readline()
                if line:
                    # drop startup noise & any HTTP headers
                    if not info_rx.search(line):
                        yield line
                    last = time.time()
                else:
                    if proc.poll() is not None:
                        break
                    # heartbeat every 5s
                    if time.time() - last >= hb_interval:
                        yield "\n"
                        last = time.time()
                    else:
                        time.sleep(0.1)

            code = proc.returncode if proc.returncode is not None else proc.wait()
            yield f"\n[ JIPipe exited with code {code} ]\n"

            shutil.rmtree(input_temp_dir)
            logger.info("Cleaned up temp dirs")

        resp = StreamingHttpResponse(stream(), content_type='text/plain')
        # if you do have an Nginx or similar reverse‐proxy in front:
        resp['Cache-Control'] = 'no-cache'
        resp['X-Accel-Buffering'] = 'no'
        return resp

    except Exception as e:
        # on error, fall back to your existing error handler
        logger.exception("Unexpected error in process_datasets")
        shutil.rmtree(input_temp_dir)
        return Response({'error': str(e)}, status=500)


@login_required()
def JIPipeRunner_index(request, project_id, conn=None, **kwargs):
    """
    Render the dataset input template for a given project.
    """
    return render(
        request,
        'JIPipeRunner/dataset_input.html',
        {'project_id': project_id}
    )


@login_required()
def getJIPipeJSON(request, project_id, conn=None, **kwargs):
    """
    Retrieve and return the JIPipe JSON annotation on a given OMERO project.
    """
    logger = logging.getLogger(__name__)
    conn.SERVICE_OPTS.setOmeroGroup('0')

    project = conn.getObject('Project', project_id)
    if project is None:
        return HttpResponse(f'Project {project_id} not found.', status=404)

    # Find first FileAnnotation
    annotation = next(
        (ann for ann in project.listAnnotations()
         if ann.OMERO_TYPE == omero.model.FileAnnotationI),
        None
    )
    if not annotation:
        return HttpResponse(f'No FileAnnotation found on Project {project_id}.', status=404)

    # Read JSON bytes
    try:
        data = b''.join(annotation.getFileInChunks())
        text = data.decode('utf-8')
        jip_json = json.loads(text)
    except Exception as e:
        logger.error("Failed to parse FileAnnotation JSON: %s", e)
        return HttpResponse(f'Error parsing JSON: {e}', status=400)

    return JsonResponse(jip_json, safe=False)


# Helper functions

def _get_or_create_results_project(conn):
    """
    Return existing JIPipeResults project or create it if missing.
    """
    name = 'JIPipeResults'
    project = conn.getObject('Project', attributes={'name': name})
    if project:
        return project

    proj = omero.model.ProjectI()
    proj.setName(rstring(name))
    proj.setDescription(rstring('Project to save all JIPipe results'))
    return conn.getUpdateService().saveAndReturnObject(proj, conn.SERVICE_OPTS)
