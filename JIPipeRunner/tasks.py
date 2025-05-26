from celery import shared_task
import json, os, tempfile, subprocess, shutil, logging
from pathlib import Path
from django.core.cache import cache
from omero.config import ConfigXml
import signal

# Turn SIGTERM into KeyboardInterrupt so you can catch it
signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt()))

@shared_task(bind=True)
def run_jipipe_task(self, project_config, job_uuid, user_name, log_file_path):
    log = logging.getLogger(__name__)

    temp_input = tempfile.mkdtemp()
    temp_output = tempfile.mkdtemp()

    try:
        jip_project_file = Path(temp_input) / 'JIPipeProject.jip'
        with open(jip_project_file, 'w') as f:
            json.dump(project_config, f)

        cfg_file = os.path.join(os.environ["OMERODIR"], "etc", "grid", "config.xml")
        cfg = ConfigXml(cfg_file, read_only=True)
        imagej_path = cfg.as_map().get("omero.web.imagej")

        command = [
            'xvfb-run', '-a', imagej_path,
            '-Dorg.apache.logging.log4j.simplelog.StatusLogger.level=ERROR',
            '-Dorg.apache.logging.log4j.simplelog.level=ERROR',
            '--memory', '8G',
            '--pass-classpath', '--full-classpath',
            '--main-class', 'org.hkijena.jipipe.cli.JIPipeCLIMain',
            'run', '--project', str(jip_project_file),
            '--output-folder', temp_output,
        ]

        with open(log_file_path, 'w') as log_file:
            log_file.write("Executable ImageJ at: " + imagej_path + "\n")
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )

            cache.set(job_uuid, process.pid, timeout=None)

            for line in process.stdout:
                log_file.write(line)
                log_file.flush()

            process.wait()
            log_file.write(f"\n[ JIPipe exited with code {process.returncode} ]\n")
    except KeyboardInterrupt:
        cfg.close()
        cache.delete(job_uuid)
        user_key = f"active_jipipe_jobs_{user_name}"
        active = set(cache.get(user_key, []))
        active.discard(job_uuid)
        cache.set(user_key, active, timeout=None)
        shutil.rmtree(temp_input)
        shutil.rmtree(temp_output)
        os.killpg(process.pid, signal.SIGTERM)
    except Exception as e:
        with open(log_file_path, 'a') as log_file:
            log_file.write(f"\nERROR in JIPipe background job: {e}\n")
        log.exception("Error in Celery JIPipe task")

    finally:
        cfg.close()
        cache.delete(job_uuid)
        user_key = f"active_jipipe_jobs_{user_name}"
        active = set(cache.get(user_key, []))
        active.discard(job_uuid)
        cache.set(user_key, active, timeout=None)
        shutil.rmtree(temp_input)
        shutil.rmtree(temp_output)
