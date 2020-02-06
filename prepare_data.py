import os
import trimesh
from tqdm import tqdm
import numpy as np
from sdf.mesh_to_sdf import MeshSDF, scale_to_unit_sphere, BadMeshException
from util import ensure_directory
from multiprocessing import Pool
from scipy.spatial.transform import Rotation

DIRECTORY_MODELS = 'data/meshes/'
MODEL_EXTENSION = '.ply'
DIRECTORY_SDF = 'data/sdf/'

CREATE_VOXELS = True
VOXEL_RESOLUTION = 128

CREATE_SDF_CLOUDS = False
SDF_CLOUD_SAMPLE_SIZE = 200000

ROTATION = np.matmul(Rotation.from_euler('x', 90, degrees=True).as_dcm(), Rotation.from_euler('z', 180, degrees=True).as_dcm())
ROTATION_HUMAN = np.matmul(Rotation.from_euler('x', -90, degrees=True).as_dcm(), Rotation.from_euler('z', 180, degrees=True).as_dcm())

def get_model_files():
    for directory, _, files in os.walk(DIRECTORY_MODELS):
        for filename in files:
            if filename.endswith(MODEL_EXTENSION):
                yield os.path.join(directory, filename)

def get_npy_filename(model_filename, qualifier=''):
    return DIRECTORY_SDF + model_filename[len(DIRECTORY_MODELS):-len(MODEL_EXTENSION)] + qualifier + '.npy'

def get_voxel_filename(model_filename):
    return get_npy_filename(model_filename, '-voxels-{:d}'.format(VOXEL_RESOLUTION))

def get_sdf_cloud_filename(model_filename):
    return get_npy_filename(model_filename, '-sdf')

def get_bad_mesh_filename(model_filename):
    return DIRECTORY_SDF + model_filename[len(DIRECTORY_MODELS):-len(MODEL_EXTENSION)] + '.badmesh'

def mark_bad_mesh(model_filename):
    filename = get_bad_mesh_filename(model_filename)
    ensure_directory(os.path.dirname(filename))            
    open(filename, 'w').close()

def is_bad_mesh(model_filename):
    return os.path.exists(get_bad_mesh_filename(model_filename))

def process_model_file(filename):
    voxels_filename = get_voxel_filename(filename)
    sdf_cloud_filename = get_sdf_cloud_filename(filename)

    if is_bad_mesh(filename):
        return
    if not (CREATE_VOXELS and not os.path.isfile(voxels_filename) or CREATE_SDF_CLOUDS and not os.path.isfile(sdf_cloud_filename)):
        return
    
    is_human = 'CMU_' in filename or 'KKI_' in filename or 'Caltech_' in filename or 'Leuven_' in filename or 'PE0' in filename

    mesh = trimesh.load(filename)
    mesh = scale_to_unit_sphere(mesh, rotation_matrix=ROTATION_HUMAN if is_human else ROTATION)

    mesh_sdf = MeshSDF(mesh, use_scans=False)
    if CREATE_SDF_CLOUDS:
        try:
            points, sdf = mesh_sdf.get_sample_points(number_of_points=SDF_CLOUD_SAMPLE_SIZE)
            combined = np.concatenate((points, sdf[:, np.newaxis]), axis=1)
            ensure_directory(os.path.dirname(sdf_cloud_filename))
            np.save(sdf_cloud_filename, combined)
        except BadMeshException:
            tqdm.write("Skipping bad mesh. ({:s})".format(filename))
            mark_bad_mesh(filename)
            return

    if CREATE_VOXELS:
        try:
            voxels = mesh_sdf.get_voxel_sdf(voxel_resolution=VOXEL_RESOLUTION)
            ensure_directory(os.path.dirname(voxels_filename))
            np.save(voxels_filename, voxels)
        except BadMeshException:
            tqdm.write("Skipping bad mesh. ({:s})".format(filename))
            mark_bad_mesh(filename)
            return


def process_model_files():
    ensure_directory(DIRECTORY_SDF)
    files = list(get_model_files())

    '''from rendering import MeshRenderer
    viewer = MeshRenderer()

    for filename in files:
        is_human = 'CMU_' in filename or 'KKI_' in filename or 'Caltech_' in filename or 'Leuven_' in filename or 'PE0' in filename

        mesh = trimesh.load(filename)
        mesh = scale_to_unit_sphere(mesh, rotation_matrix=ROTATION_HUMAN if is_human else ROTATION)
        print(filename)
        viewer.set_mesh(mesh)
        viewer.model_color = (0.8, 0.0, 0.0) if is_human else (1.0, 0.5, 0.5)
        import time
        time.sleep(1)
    '''
    
    worker_count = os.cpu_count()
    print("Using {:d} processes.".format(worker_count))
    pool = Pool(worker_count)

    progress = tqdm(total=len(files))
    def on_complete(*_):
        progress.update()

    for filename in files:
        pool.apply_async(process_model_file, args=(filename,), callback=on_complete)
    pool.close()
    pool.join()

def combine_pointcloud_files():
    import torch
    print("Combining SDF point clouds...")
    npy_files = sorted([get_sdf_cloud_filename(f) for f in get_model_files()])
    npy_files = [f for f in npy_files if os.path.exists(f)]
    
    N = len(npy_files)
    points = torch.zeros((N * SDF_CLOUD_SAMPLE_SIZE, 3))
    sdf = torch.zeros((N * SDF_CLOUD_SAMPLE_SIZE))
    position = 0

    for npy_filename in tqdm(npy_files):
        numpy_array = np.load(npy_filename)
        points[position * SDF_CLOUD_SAMPLE_SIZE:(position + 1) * SDF_CLOUD_SAMPLE_SIZE, :] = torch.tensor(numpy_array[:, :3])
        sdf[position * SDF_CLOUD_SAMPLE_SIZE:(position + 1) * SDF_CLOUD_SAMPLE_SIZE] = torch.tensor(numpy_array[:, 3])
        del numpy_array
        position += 1
    
    print("Saving combined SDF clouds...")
    torch.save(points, os.path.join('data', 'sdf_points.to'))
    torch.save(sdf, os.path.join('data', 'sdf_values.to'))

def combine_voxel_files():
    import torch
    print("Combining voxels...")
    npy_files = sorted([get_voxel_filename(f) for f in get_model_files()])
    npy_files = [f for f in npy_files if os.path.exists(f)]

    N = len(npy_files)
    result = torch.zeros((N, VOXEL_RESOLUTION, VOXEL_RESOLUTION, VOXEL_RESOLUTION))
    
    position = 0
    for npy_filename in tqdm(npy_files):
        numpy_array = np.load(npy_filename)
        result[position, :, :, :] = torch.tensor(numpy_array)
        del numpy_array
        position += 1

    filename = os.path.join('data', 'voxels-{:d}.to'.format(VOXEL_RESOLUTION))
    print("Saving voxel data to {:s}...".format(filename))
    torch.save(result, filename)

if __name__ == '__main__':
    process_model_files()
    if CREATE_SDF_CLOUDS:
        combine_pointcloud_files()
    if CREATE_VOXELS:
        combine_voxel_files()