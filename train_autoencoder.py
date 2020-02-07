from itertools import count

import torch
import torch.nn as nn
import torch.optim as optim

import random
random.seed(0)
torch.manual_seed(0)

import numpy as np

import sys
import time

from model.autoencoder import Autoencoder

from collections import deque

from dataset import dataset as dataset
from util import create_text_slice, device
dataset.load_voxels(device)


BATCH_SIZE = 16

training_indices = list(range(dataset.size))

VIEWER_UPDATE_STEP = 20

IS_VARIATIONAL = 'classic' not in sys.argv

autoencoder = Autoencoder(is_variational=IS_VARIATIONAL)
if "continue" in sys.argv:
    autoencoder.load()

optimizer = optim.Adam(autoencoder.parameters(), lr=0.00002)

show_viewer = "nogui" not in sys.argv

if show_viewer:
    from rendering import MeshRenderer
    viewer = MeshRenderer()

error_history = deque(maxlen = dataset.voxels.shape[0] // BATCH_SIZE)

criterion = nn.functional.mse_loss

log_file = open("plots/{:s}autoencoder_training.csv".format('variational_' if autoencoder.is_variational else ''), "a" if "continue" in sys.argv else "w")

def voxel_difference(input, target):
    wrong_signs = (input * target) < 0
    return torch.sum(wrong_signs).item() / wrong_signs.nelement()

def kld_loss(mean, log_variance):
    return -0.5 * torch.sum(1 + log_variance - mean.pow(2) - log_variance.exp()) / mean.nelement()

def create_batches():
    batch_count = int(len(training_indices) / BATCH_SIZE)
    random.shuffle(training_indices)
    for i in range(batch_count - 1):
        yield training_indices[i * BATCH_SIZE:(i+1)*BATCH_SIZE]
    yield training_indices[(batch_count - 1) * BATCH_SIZE:]

def get_reconstruction_loss(input, target):
    difference = input - target
    wrong_signs = target < 0
    difference[wrong_signs] *= 32

    return torch.mean(torch.abs(difference))

def test(epoch_index, epoch_time):
    reconstruction_loss = np.mean(error_history)
    print("Epoch {:d} ({:.1f}s): ".format(epoch_index, epoch_time) +
        "training loss: {:4f}, ".format(reconstruction_loss)
    )

    log_file.write('{:d} {:.1f} {:.6f}\n'.format(epoch_index, epoch_time, reconstruction_loss))
    log_file.flush()

def train():    
    for epoch in count():
        batch_index = 0
        epoch_start_time = time.time()
        for batch in create_batches():
            try:
                indices = torch.tensor(batch, device=device)
                sample = dataset.voxels[indices, :, :, :]

                autoencoder.zero_grad()
                autoencoder.train()
                if IS_VARIATIONAL:
                    output, mean, log_variance = autoencoder(sample)
                    kld = kld_loss(mean, log_variance)
                else:
                    output = autoencoder(sample)
                    kld = 0

                reconstruction_loss = get_reconstruction_loss(output, sample)
                error_history.append(reconstruction_loss.item())

                loss = reconstruction_loss + kld
                
                loss.backward()
                optimizer.step()

                if show_viewer and batch_index == 0:
                    viewer.set_voxels(output[0, :, :, :].squeeze().detach().cpu().numpy())

                if show_viewer and (batch_index + 1) % VIEWER_UPDATE_STEP == 0 and 'verbose' in sys.argv:
                    viewer.set_voxels(output[0, :, :, :].squeeze().detach().cpu().numpy())
                    print("epoch " + str(epoch) + ", batch " + str(batch_index) \
                        + ', reconstruction loss: {0:.4f}'.format(reconstruction_loss.item()) \
                        + ' (average: {0:.4f}), '.format(sum(error_history) / len(error_history)) \
                        + 'KLD loss: {0:.4f}'.format(kld))
                batch_index += 1
            except KeyboardInterrupt:
                if show_viewer:
                    viewer.stop()
                return
        autoencoder.save()
        if epoch % 20 == 0:
            autoencoder.save(epoch=epoch)
        test(epoch, time.time() - epoch_start_time)

train()