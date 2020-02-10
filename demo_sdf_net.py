from model.sdf_net import SDFNet, LATENT_CODE_SIZE, LATENT_CODES_FILENAME
from util import device, standard_normal_distribution, ensure_directory
import scipy
import numpy as np
from rendering import MeshRenderer
import time
import torch
from tqdm import tqdm
import cv2
import random
import sys

SAMPLE_COUNT = 30 # Number of distinct objects to generate and interpolate between
TRANSITION_FRAMES = 60

ROTATE_MODEL = False
USE_HYBRID_GAN = False

SURFACE_LEVEL = 0 #0.048 if USE_HYBRID_GAN else 0.02

sdf_net = SDFNet()
if USE_HYBRID_GAN:
    sdf_net.filename = 'hybrid_progressive_gan_generator_2.to'
sdf_net.load()
sdf_net.eval()


codes = torch.load(LATENT_CODES_FILENAME).detach().cpu().numpy()
SAMPLE_COUNT = codes.shape[0] - 1

codes[0, :] = codes[-1, :] # Make animation periodic
spline = scipy.interpolate.CubicSpline(np.arange(SAMPLE_COUNT + 1), codes, axis=0, bc_type='periodic')

def create_image_sequence():
    ensure_directory('images')
    frame_index = 0
    viewer = MeshRenderer(size=1080, start_thread=False)
    progress_bar = tqdm(total=SAMPLE_COUNT * TRANSITION_FRAMES)

    for sample_index in range(SAMPLE_COUNT):
        for step in range(TRANSITION_FRAMES):
            code = torch.tensor(spline(float(sample_index) + step / TRANSITION_FRAMES), dtype=torch.float32, device=device)
            if ROTATE_MODEL:
                viewer.rotation = (147 + frame_index / (SAMPLE_COUNT * TRANSITION_FRAMES) * 360 * 6, 40)
            viewer.set_mesh(sdf_net.get_mesh(code, voxel_resolution=128, sphere_only=False, level=SURFACE_LEVEL))
            image = viewer.get_image(flip_red_blue=True)
            cv2.imwrite("images/frame-{:05d}.png".format(frame_index), image)
            frame_index += 1
            progress_bar.update()
    
    print("\n\nUse this command to create a video:\n")
    print('ffmpeg -framerate 30 -i images/frame-%05d.png -c:v libx264 -profile:v high -crf 19 -pix_fmt yuv420p video.mp4')

def show_models():
    TRANSITION_TIME = 2
    viewer = MeshRenderer()

    while True:
        for sample_index in range(SAMPLE_COUNT):
            try:
                start = time.perf_counter()
                end = start + TRANSITION_TIME
                while time.perf_counter() < end:
                    progress = min((time.perf_counter() - start) / TRANSITION_TIME, 1.0)
                    if ROTATE_MODEL:
                        viewer.rotation = (147 + (sample_index + progress) / SAMPLE_COUNT * 360 * 6, 40)
                    code = torch.tensor(spline(float(sample_index) + progress), dtype=torch.float32, device=device)
                    viewer.set_mesh(sdf_net.get_mesh(code, voxel_resolution=64, sphere_only=False, level=SURFACE_LEVEL))
                
            except KeyboardInterrupt:
                viewer.stop()
                return

def create_objects():
    from util import ensure_directory
    from rendering.raymarching import render_image
    import os
    ensure_directory('generated_objects/')
    image_filename = 'generated_objects/{:05d}.png'
    mesh_filename = 'generated_objects/{:05d}.ply'
    index = 0
    for index in range(codes.shape[0]):
        if os.path.exists(image_filename.format(index)) or os.path.exists(mesh_filename.format(index)):
            continue
        latent_code = codes[index, :].to(device)
        image = render_image(sdf_net, latent_code, resolution=256, sdf_offset=-SURFACE_LEVEL, ssaa=2, radius=1.4, color=(0.7, 0.7, 0.7))
        image.save(image_filename.format(index))
        mesh = sdf_net.get_mesh(latent_code, voxel_resolution=128, sphere_only=False, level=SURFACE_LEVEL)
        mesh.export(mesh_filename.format(index))
        print("Created mesh for index {:d}".format(index))


if 'save' in sys.argv:
    create_image_sequence()
elif 'create_objects' in sys.argv:
    create_objects()
else:
    show_models()