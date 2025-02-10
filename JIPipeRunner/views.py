from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from .forms import RangeInputForm
from .models import IDs
from omeroweb.decorators import login_required
import omero.clients
import omero.gateway
import os
import tempfile
from pathlib import Path
import subprocess
import shutil
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
import numpy as np
import omero
import omero.model
from omero.rtypes import rstring
import logging
import json
import getpass
from PIL import Image
import cv2

EXTENSION_TO_FORMAT = {
        '.jpg': 'JPEG',
        '.jpeg': 'JPEG',
        '.png': 'PNG',
        '.tiff': 'TIFF',
        '.tif': 'TIFF',
        '.bmp': 'BMP',
        # Add more mappings as needed
    }


@api_view(['POST'])
@login_required()
def process_datasets(request, conn=None, **kwargs):

    # Enable logging
    logger = logging.getLogger(__name__)
    """
    # Get all the groups that the current user is a member of
    logger.info("Listing user groups...")
    groups = conn.getGroupsMemberOf()
    logger.info("Current working directory: %s", os.getcwd())

    logger.info("getpass.getuser() => %s", getpass.getuser())
    if os.name != 'nt':  # Check if the operating system is not Windows
        home_dir = os.environ.get("HOME", "HOME environment variable not set")
        logger.info("HOME => %s", home_dir)

    for grp in groups:
        group_id = grp.getId()
        group_name = grp.getName()
        # The Permissions object shows the read/write restrictions
        perms_obj = grp.getDetails().getPermissions()
        
        # Permissions can be directly printed, or you can test specific flags
        # e.g. perms_obj.isGroupWrite(), perms_obj.isGroupRead(), etc.
        logger.info(f"Group: {group_name} (ID: {group_id}) - Permissions: {perms_obj}")
    """
    
    # --- 1) Parse query parameters ---
    # Set the group to 0 to allow access to all groups
    conn.SERVICE_OPTS.setOmeroGroup('0')

    # Get the dataset IDs and the target project ID from the query parameters
    """
    ids_str = request.GET.get('ids')
    project_id = int(request.GET.get('project_id'))
    if not ids_str or not project_id:
        return Response({'error': 'Missing "ids" or "project_id" parameter'}, status=400)
    """

    # Convert the comma-separated string of IDs to a list of integers
    """
    dataset_ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
    dataset_list = [conn.getObject("Dataset", ds_id) for ds_id in dataset_ids]
    dataset_list = [ds for ds in dataset_list if ds is not None]
    if not dataset_list:
        return Response({'error': 'No valid dataset found'}, status=404)
    """

    
    # --- 2) Get the target Project ---
    """
    project_obj = conn.getObject("Project", project_id)
    if not project_obj:
        return Response({'error': f'Project ID {project_id} not found'}, status=404)
    """
    
    # --- 3) Create temporary input/output directories ---
    input_temp_dir = tempfile.mkdtemp()
    input_temp_path = Path(input_temp_dir)
    logger.info("Input temp directory: %s", input_temp_path)
    output_temp_dir = tempfile.mkdtemp()
    output_temp_path = Path(output_temp_dir)


    try:
        # --- 4) Save .jip file to input_temp---

        # --- 5) Put the images from the input datasets into tmp subdirectories ---
        """
        for dataset in dataset_list:
            # Create subdirectory according to results_dataset name
            dataset_name = dataset.getName()
            dataset_path = os.path.join(input_temp_path, dataset_name)
            os.mkdir(dataset_path)

            # add images to subdirectory
            for image in dataset.listChildren():
                try:
                    # Extract the image name and extension
                    image_name = image.getName()
                    base_name, ext = os.path.splitext(image_name)
                    
                    # Normalize the extension to lowercase
                    ext = ext.lower()
                    
                    if not ext:
                        raise ValueError(f"No file extension found for image '{image_name}'.")
                    
                    # Determine the Pillow format
                    img_format = EXTENSION_TO_FORMAT[ext]
                    if not img_format:
                        raise ValueError(f"Unsupported file extension '{ext}' for image '{image_name}'.")
                    
                    # Retrieve pixel data
                    pixels = image.getPrimaryPixels()
                    plane = pixels.getPlane(0, 0, 0)  # Get the first plane
                    
                    # Convert plane data to a NumPy array if it's not already
                    if not isinstance(plane, np.ndarray):
                        plane = np.array(plane)
                    
                    # Handle different image modes based on data shape and type
                    if plane.ndim == 2:
                        # Grayscale image
                        mode = 'L' if plane.dtype == np.uint8 else 'I;16'  # Adjust mode based on dtype
                    elif plane.ndim == 3:
                        if plane.shape[2] == 3:
                            # RGB image
                            mode = 'RGB'
                        elif plane.shape[2] == 4:
                            # RGBA image
                            mode = 'RGBA'
                        else:
                            raise ValueError(f"Unsupported number of channels ({plane.shape[2]}) in image '{image_name}'.")
                    else:
                        raise ValueError(f"Unsupported image dimensions {plane.shape} for image '{image_name}'.")
                    
                    # Create a PIL Image from the NumPy array
                    img = Image.fromarray(plane, mode=mode)
                    
                    # Define the full path for saving the image
                    image_file_path = os.path.join(dataset_path, image_name)
                    
                    # Save the image with the determined format
                    img.save(image_file_path, format=img_format)
                    
                    logger.info(f"Successfully wrote {image_file_path} as format {img_format}")
                
                except Exception as e:
                    logger.info(f"Failed to write {image_name}: {e}")
        """



        # --- 6) Create a new results_dataset or use an existing one to store results ---
        """
        results_dataset_name = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results_dataset_description = "Dataset to save JIPipe results of a given timestemp"
        results_dataset = omero.model.DatasetI()
        results_dataset.setName(rstring(results_dataset_name))
        results_dataset.setDescription(rstring(results_dataset_description))
        results_dataset = conn.getUpdateService().saveAndReturnObject(results_dataset, conn.SERVICE_OPTS)
        """


        # --- 7) Create a JIPipeResults project if it does not exist ---
        results_project_name = "JIPipeResults"
        results_project_description = "Project to save all JIPipe results"

        results_project = conn.getObject("Project", attributes={"name": results_project_name})
        if not results_project:
            results_project = omero.model.ProjectI()
            results_project.setName(rstring(results_project_name))
            results_project.setDescription(rstring(results_project_description))
            results_project = conn.getUpdateService().saveAndReturnObject(results_project, conn.SERVICE_OPTS)

        # Get results_project id
        results_project_id = int(results_project.getId())

        # modify jipipe_file as necessary
        jipipe_file_str = request.body.decode('utf-8')  # raw JSON string
        jipipe_file_json = json.loads(jipipe_file_str)  # dict in Python

        logger.info("Received JSON: %s", jipipe_file_str)
        for node in jipipe_file_json["graph"]["nodes"].values():
            if "define-project-ids" in node["jipipe:alias-id"].lower():
                node["dataset-ids"] = [results_project_id]

        # Write the modified data to a new JSON file
        jipipe_file_path = f"{input_temp_path}/JIPipeProject.jip"
        with open(jipipe_file_path, 'w') as f:
            json.dump(jipipe_file_json, f)

        # --- 8) Link the results_dataset to the results Project ---
        """
        link = omero.model.ProjectDatasetLinkI()
        link.setChild(omero.model.DatasetI(results_dataset.getId(), False))
        link.setParent(omero.model.ProjectI(results_project.getId(), False))
        conn.getUpdateService().saveObject(link)
        """

        # --- 9) Execute the JIPipe CLI using the temporary directories ---
        path_to_jipipe = Path("/opt/JIPipe-4.2/Fiji.app/ImageJ-linux64") #TODO: Find this dynamically

        """
        user_directory_json_path = input_temp_path / "user_directories.json"

        # Check if the JSON file already exists
        if not user_directory_json_path.exists():
            # Create a dictionary with the required keys
            data = {
                "Input": str(input_temp_path),
                "Output": str(output_temp_path)
            }

            # Write the dictionary to the JSON file
            with user_directory_json_path.open('w') as json_file:
                json.dump(data, json_file, indent=4)
        """


        # TODO: Make command not hardcoded (read user directories from .jip file)
        # TODO: Check --overwrite-user-directories flag. Doesn't seem to work as intended
        # "--overwrite-user-directories", str(user_directory_json_path)
        # "--UInput", str(input_temp_path),
        # "--UOutput", str(output_temp_path),
        command = [
            "xvfb-run",
            str(path_to_jipipe),
            "--memory", "8G",
            "--pass-classpath",
            "--full-classpath",
            "--main-class", "org.hkijena.jipipe.cli.JIPipeCLIMain",
            "run",
            "--project", jipipe_file_path,
            "--output-folder", str(output_temp_path)
        ]

        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # --- 10) Copy images from the output directory to the results_dataset ---
        """
        allowed_extensions = {'.png', '.jpeg', '.jpg', '.bmp', '.avi', '.tiff'}
        
        for root, dirs, files in os.walk(output_temp_path):
            for file in files:
                # Check if the file has an allowed extension
                if Path(file).suffix.lower() in allowed_extensions:
                    # Construct full file path
                    file_path = Path(root) / file

                    im = cv2.imread(file_path)
                    size_z, size_c, size_t = len(im[0]), len(im[1])

                    logger.info("Image shape: %s", im.shape)

                    i = conn.createImageFromNumpySeq(
                        plane_gen(), image.getName(), size_z, size_c, size_t, description='',
                        dataset=results_dataset)
        """



        # --- 11) Copy images from the selected datasets to the results_dataset ---
        """
        for ds in dataset_list:
            for image in ds.listChildren():
                size_z, size_c, size_t = image.getSizeZ(), image.getSizeC(), image.getSizeT()
                pixels = image.getPrimaryPixels()
                logger.info("Image: %s, size_z: %s, size_c: %s, size_t: %s", image.getName(), size_z, size_c, size_t)
                logger.info("Image shape: %s", pixels.getPlane(0,0,0).shape)
                def plane_gen():
                    for z in range(size_z):
                        for c in range(size_c):
                            for t in range(size_t):
                                new_plane = pixels.getPlane(z, c, t)  #TODO: make this work for bigger images (greater than 3000x3000 px)
                                yield new_plane

                i = conn.createImageFromNumpySeq(
                plane_gen(), image.getName(), size_z, size_c, size_t, description='',
                dataset=results_dataset)
    except subprocess.CalledProcessError as e:
        logger.error("Command failed with return code %s", e.returncode)
        logger.error("STDOUT:\n%s", e.stdout)
        logger.error("STDERR:\n%s", e.stderr)
        raise

    data = [{
        'id': ds.getId(),
        'name': ds.getName(),
        'project_id': project_id
    } for ds in dataset_list]
        """
    
    except Exception as e:
        logger.error("An error occurred: %s", e)
        return Response({'error': f'An error occurred: {e}'}, status=500)
    finally:
        # --- Always clean up temporary directories ---
        shutil.rmtree(input_temp_dir)
        #shutil.rmtree(output_temp_dir)
        logger.info("Temporary directories cleaned up!")


    return Response("Images successfully processed, refresh the page to see the results in the results project!")

def JIPipeRunner_index(request, project_id):
    return render(request, 'JIPipeRunner/dataset_input.html', {'project_id': project_id})

from django.http import JsonResponse, HttpResponse
import json

@login_required()
def getJIPipeJSON(request, project_id, conn=None, **kwargs):
    """
    Retrieve the JIPipe JSON file associated with a given project.
    """

    logger = logging.getLogger(__name__)
    logger.info("getJIPipeJSON called with project_id=%s", project_id)

    # Switch group if needed
    conn.SERVICE_OPTS.setOmeroGroup('0')
    
    # Get the Project
    project = conn.getObject("Project", project_id)
    if project is None:
        return HttpResponse(f"Project {project_id} not found.", status=404)

    # Loop over annotations, find first FileAnnotation
    file_annotation = None
    for ann in project.listAnnotations():
        if ann.OMERO_TYPE == omero.model.FileAnnotationI:
            file_annotation = ann
            break

    if not file_annotation:
        return HttpResponse(f"No FileAnnotation found on Project {project_id}.", status=404)

    # Download the file contents from OMERO
    file_content_iterator = file_annotation.getFileInChunks()
    file_bytes = b"".join(file_content_iterator)  # combine into single bytes object
    
    # Convert to string, parse as JSON
    try:
        file_str = file_bytes.decode("utf-8")  # if it's UTF-8 JSON
        jipipe_json = json.loads(file_str)
    except Exception as e:
        return HttpResponse("Error parsing JSON: " + str(e), status=400)
    
    # Return the JSON
    return JsonResponse(jipipe_json, safe=False)




