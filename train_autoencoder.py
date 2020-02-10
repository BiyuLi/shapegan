from itertools import count

import torch
import torch.nn as nn
import torch.optim as optim
from datasets import VoxelDataset
from torch.utils.data import DataLoader

import random
random.seed(0)
torch.manual_seed(0)

import numpy as np
import sys
import time
from tqdm import tqdm

from model.autoencoder import Autoencoder
from collections import deque
from util import create_text_slice, device

# running it with AE: `python3 train_autoencoder.py classic nogui continue`
# with VAE: `python3 train_autoencoder.py nogui continue`
# running it for the first time: without `continue` argument

BATCH_SIZE = 16
# number of specimens shown to network at once
# increase this number to get better result (training more stable), but it takes longer!
# influences vRAM GPUram! --> if we get ram error, reduce batch size
# if training is stable, there's no reason to change it; otherwise we can increase as long as we do not run into memory error

VIEWER_UPDATE_STEP = 20
# if you have screen, you will see update after 20 steps

IS_VARIATIONAL = 'classic' not in sys.argv
# to use VAE insteads of AE, do not define this as an argument in the command line --> VAE is default

autoencoder = Autoencoder(is_variational=IS_VARIATIONAL)
if "continue" in sys.argv:
    autoencoder.load()

optimizer = optim.Adam(autoencoder.parameters(), lr=0.00002)
# learn rate; now at =0.00002; network uses gradient of error, they are multiplied with the learn rate 
# --> so if learn rate is very small it will change the network params a little
# the smaller the number, the more stable the training will be, the longer it will take
# goal: lr as high as possible without breaking the training process
# if lr too high: loss value does not get smaller anymore (overshooting: it optimizes in right direction, but will go too far, no descent anymore)

# Adam: adaptive moment optimisziation: there are different optimizers, the one we use is RMSprop; Adam is default; Root means square propagation


dataset = VoxelDataset.glob('data/sdf-volumes/**/*.npy')
data_loader = DataLoader(dataset, shuffle=True, batch_size=BATCH_SIZE, num_workers=8)

show_viewer = "nogui" not in sys.argv

if show_viewer:
    from rendering import MeshRenderer
    viewer = MeshRenderer()

error_history = deque(maxlen=len(dataset) // BATCH_SIZE)


log_file = open("plots/{:s}autoencoder_training.csv".format('variational_' if autoencoder.is_variational else ''), "a" if "continue" in sys.argv else "w")


def kld_loss(mean, log_variance):
    # obtain normally distributed latent space
    return -0.5 * torch.sum(1 + log_variance - mean.pow(2) - log_variance.exp()) / mean.nelement()
    # used in VAE: the Kullback Leibler divergence; will push the distribution of the latent space towards the normal distribution

# def voxel_difference(input, target):
#     # calculate difference between learnt by network and ground truth
#     wrong_signs = (input * target) < 0

#     return torch.sum(wrong_signs).item() / wrong_signs.nelement()
# Boosts the error of voxels with wrong signs, as these influence the Marching Cubes reconstructed surface more.
# network will put in twice the effort to fix the important errors; here: diff sdf volumes in and learnt 
def get_reconstruction_loss(input, target):
    difference = input - target
    wrong_signs = (input * target) < 0
    difference[wrong_signs] *= 32

    return torch.mean(torch.abs(difference))

criterion = nn.functional.mse_loss
# criterion = get_reconstruction_loss
# 32 can be changed to any number

def print_training_stats(epoch_index, epoch_time):
    reconstruction_loss = np.mean(error_history)
    print("Epoch {:d} ({:.1f}s): ".format(epoch_index, epoch_time) +
        "training loss: {:4f}, ".format(reconstruction_loss)
    )

    # log csv file: epoch_index, epoch_time, reconstruction_loss written to csv file; reco loss is the mean of the last epoch
    log_file.write('{:d} {:.1f} {:.6f}\n'.format(epoch_index, epoch_time, reconstruction_loss))
    log_file.flush()

def train():    
    for epoch in count():
        batch_index = 0
        epoch_start_time = time.time()
        for batch in tqdm(data_loader, desc='Epoch {:d}'.format(epoch)):
            try:
                batch = batch.to(device)

                autoencoder.zero_grad()
                autoencoder.train()
                if IS_VARIATIONAL:
                    output, mean, log_variance = autoencoder(batch)
                    kld = kld_loss(mean, log_variance)
                else:
                    output = autoencoder(batch)
                    kld = 0

                reconstruction_loss = criterion(output, batch)
                error_history.append(reconstruction_loss.item())

                loss = reconstruction_loss + kld
                # calc gradient of every variable in network with regard to loss function (pyTorch functionality)
                loss.backward()
                # updates network params using these gradients
                optimizer.step()

                if show_viewer and batch_index == 0:
                    viewer.set_voxels(output[0, :, :, :].squeeze().detach().cpu().numpy())

                if show_viewer and (batch_index + 1) % VIEWER_UPDATE_STEP == 0 and 'verbose' in sys.argv:
                    viewer.set_voxels(output[0, :, :, :].squeeze().detach().cpu().numpy())
                    print("epoch " + str(epoch) + ", batch " + str(batch_index) \
                        + ', reconstruction loss: {0:.4f}'.format(reconstruction_loss.item()))
                batch_index += 1
            except KeyboardInterrupt:
                if show_viewer:
                    viewer.stop()
                return
        autoencoder.save()
        if epoch % 20 == 0:
            # save copy of network after every 20 steps, to check the training --> output in `models/checkpoints`
            autoencoder.save(epoch=epoch)
        print_training_stats(epoch, time.time() - epoch_start_time)

train()