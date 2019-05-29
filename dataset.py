import os
import json
import numpy as np
from tqdm import tqdm
import torch

from voxel.binvox_rw import read_as_3d_array
from scipy.ndimage import zoom

DATASET_DIRECTORY = "/home/marian/shapenet/ShapeNetCore.v2/"
MIN_SAMPLES_PER_CLASS = 500
VOXEL_SIZE = 32
MODELS_FILENAME = "data/dataset.to"
LABELS_FILENAME = "data/labels.to"

class DataClass():
    def __init__(self, name, id, count):
        self.name = name
        self.id = id
        self.is_root = True
        self.children = []
        self.count = count

    def print(self, depth = 0):
        if self.count < MIN_SIZE:
            return
        print('  ' * depth + self.name + '({:d})'.format(self.count))
        for child in self.children:
            child.print(depth = depth + 1)

class Dataset():
    def __init__(self):
        self.prepare_class_data()

    def prepare_class_data(self):
        taxonomy_filename = os.path.join(DATASET_DIRECTORY, "taxonomy.json")
        file_content = open(taxonomy_filename).read()
        taxonomy = json.loads(file_content)
        classes = dict()
        for item in taxonomy:
            id = int(item['synsetId'])
            dataclass = DataClass(item['name'], id, item['numInstances'])
            classes[id] = dataclass

        for item in taxonomy:
            id = int(item['synsetId'])
            dataclass = classes[id]
            for str_id in item["children"]:
                child_id = int(str_id)
                dataclass.children.append(classes[child_id])
                classes[child_id].is_root = False
        
        self.classes = [item for item in classes.values() if item.is_root and item.count >= MIN_SAMPLES_PER_CLASS]
        self.label_count = len(self.classes)

    def prepare(self):
        labels = []
        filenames = []

        print("Scanning directory...")        
        for label in range(len(self.classes)):
            current_class = self.classes[label]
            items_in_class = 0
            class_directory = os.path.join(DATASET_DIRECTORY, str(current_class.id).rjust(8, '0'))
            for subdirectory in os.listdir(class_directory):
                filename = os.path.join(class_directory, subdirectory, "models" , "model_normalized.solid.binvox")
                if os.path.isfile(filename):
                    filenames.append(filename)
                    items_in_class += 1

            labels.append(torch.ones(items_in_class) * label)
            
        models = []
        pool = torch.nn.MaxPool3d(4)
        print("Loading models...")
        for filename in tqdm(filenames):
            voxels = torch.tensor(read_as_3d_array(open(filename, 'rb')).data.astype(np.float32)) * 2 - 1
            voxels = torch.unsqueeze(voxels, 0)
            voxels = pool(voxels).squeeze()
            models.append(voxels.to(torch.int8))
        
        print("Saving...")
        tensor = torch.stack(models).to(torch.int8)
        torch.save(tensor, MODELS_FILENAME)

        labels = torch.cat(labels).to(torch.int8)
        torch.save(labels, LABELS_FILENAME)

        print("Done.")

    def load(self, device):
        print("Loading dataset...")
        self.voxels = torch.load(MODELS_FILENAME).float().to(device)
        self.size = self.voxels.shape[0]
        self.label_indices = torch.load(LABELS_FILENAME).to(torch.int64).to(device)
        self.labels = torch.zeros((self.size, self.label_count))
        self.labels[torch.arange(0, self.size, dtype=torch.long, device=device), self.label_indices] = 1
        self.labels = self.labels.to(device)


dataset = Dataset()
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

if __name__ == "__main__":
    dataset.prepare()
else:
    dataset.load(device)